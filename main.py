# current status: stable,
# highlights work

# works with: Start_Page.ui, Patient_Summary.ui
# * created by Qt Designer
# logo.png will define program symbol
# put your .wav files in records/user0, and name them as noted in FILE_LIST below
# create more user folders when needed

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import sys
import time
import wave
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5 import uic, QtGui, QtCore, QtWidgets
from PyQt5.QtCore import QUrl, QFileInfo, pyqtSlot
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtWidgets import QMessageBox


matplotlib.use('Qt5Agg')

# constants
START_PAGE = "Start_Page.ui"
PATIENT_SUMMARY_PAGE = "Patient_Summary.ui"
# TODO: we might add another .ui file if necessary
WINDOW_ICON = "logo.png"
CHANNEL_LIST = ["Channel 1", "Channel 2", "Channel 3", "Channel 4"]
REL_PATH = "records/user"   # relative file path
USER_LIST = ["User 1", "User 2"]  # , "User 3", "User 4"]
FILE_LIST = ["/channel_1.wav", "/channel_2.wav", "/channel_3.wav", "/channel_4.wav"]
MAX_ZOOM = 40
BG_BLACK = (0, 0, 0)
BG_GRAY = (0.3, 0.3, 0.3)
MIN_WIDTH = 400  # minimum width for patient window
MIN_HEIGHT = 500  # minimum height for patient window
FIXED_HEIGHT = 200 + 73  # button layout + slider
WIN_X = 800  # initial window width
WIN_Y = 603  # initial window height
UPDATE_INTERVAL = 1  # msec
SAMPLE_COUNT = 96000-1  # depends on .wav file
# TODO: get sample count from the file
SCATTER_COLORS = ["red", "blue", "white"]   # fine, coarse, wheeze
HIGHLIGHT_WIDTH = 1000


# mini function for messageboxes
def PopUp(title="Info", text="Problem", icon="Info", enabled=True):
    # Message box
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(text)
    if icon == "Info":
        msg.setIcon(QMessageBox.Information)
    if enabled:
        msg.exec_()


# first window, for selecting patient
class StartPage(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = uic.loadUi(START_PAGE, self)    # connect the class to .ui file
        self.resize(730, 500)                       # resize window

        # set window icon
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(WINDOW_ICON), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.setWindowIcon(icon)

        self.currentName = ""
        self.patientNumber = -1

        # connecting inputs to signals
        # 1. dropdown menu items
        self.actionUser1.triggered.connect(lambda value, x=1: self.setPatient(x))
        self.actionUser2.triggered.connect(lambda value, x=2: self.setPatient(x))
        self.actionUser3.triggered.connect(lambda value, x=3: self.setPatient(x))
        self.actionUser4.triggered.connect(lambda value, x=4: self.setPatient(x))
        # 2. line edit
        self.lineEdit.setPlaceholderText("Enter the patient name")
        self.lineEdit.textChanged['QString'].connect(lambda value, x=5: self.setPatient(x, value))
        self.lineEdit.returnPressed.connect(self.startPatient)
        # 3. button click
        self.pushButton.clicked.connect(self.startPatient)

    # set patient
    def setPatient(self, x, value=None):
        # from menu
        if x < 5:
            self.patientNumber = x - 1
            self.lineEdit.setText("User{} is selected".format(x))
            self.lineEdit.setEnabled(False)
        # by name
        else:
            self.currentName = value

    # start new window based on patient
    def startPatient(self):
        # find patient by name
        if self.currentName in USER_LIST and self.lineEdit.isEnabled():
            self.patientNumber = USER_LIST.index(self.currentName)
            patientWindow = PatientSummary(self.patientNumber)
            patientWindow.show()
            patientWindow.patientWindow = self
            self.hide()
        elif self.currentName not in USER_LIST and self.lineEdit.isEnabled():
            # Message box
            PopUp("Information", "Patient not found!")
        # find patient by number
        else:
            patientWindow = PatientSummary(self.patientNumber)
            patientWindow.show()
            patientWindow.patientWindow = self
            self.hide()


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        # self.fig.tight_layout()
        # TODO: call resize function for tight layout


class Worker(QtCore.QRunnable):
    # TODO: Compare this with QtConcurrent
    def __init__(self, function, *args, **kwargs):
        super(Worker, self).__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):
        self.function(*self.args, **self.kwargs)


class PatientSummary(QtWidgets.QMainWindow):
    def __init__(self, patientNumber):
        super().__init__()
        self.patientNumber = patientNumber
        self.ui = uic.loadUi(PATIENT_SUMMARY_PAGE, self)    # connect the class to .ui file
        print(self.size().width(), self.size().height())
        self.resize(WIN_X, WIN_Y)                           # resize window

        # set icon
        icon = QtGui.QIcon()
        icon.addPixmap(QtGui.QPixmap(WINDOW_ICON), QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.setWindowIcon(icon)

        # initialize some fields for later use
        self.plotWindow = None      # for optional new plot window
        self.signal = []            # for data that will be plotted
        self.maximum = 0            # signal max
        self.minimum = 0            # signal min

        # thread pool for responsive playback
        self.threadpool = QtCore.QThreadPool()

        # radio list for channel
        self.radioButton.toggled.connect(lambda value, x=1: self.setChannel(value, x))
        self.radioButton_2.toggled.connect(lambda value, x=2: self.setChannel(value, x))
        self.radioButton_3.toggled.connect(lambda value, x=3: self.setChannel(value, x))
        self.radioButton_4.toggled.connect(lambda value, x=4: self.setChannel(value, x))
        self.channel = 0  # selected channel

        # initializing the length of the live plot according to zoomRate
        self.zoomRate = 1
        self.length = int(SAMPLE_COUNT / self.zoomRate)

        # zoom slider + lineEdit
        self.horizontalSlider.valueChanged.connect(lambda value: self.zoomSlider(value))
        self.horizontalSlider.sliderReleased.connect(self.sliderReleaseHandler)
        self.lineEdit.returnPressed.connect(self.zoomEdit)

        # Pause checkbox
        self.checkBox.stateChanged.connect(self.updatePause)
        self.mypause = 0  # 0 means: yes, pause

        # Plotting options
        # 1. Checkbox
        self.checkBox_2.stateChanged.connect(self.updateNewWindowPlotting)
        self.plotInNewWindow = 0
        # 2. Combobox
        self.selectedAnomaly = -1
        self.comboBox.currentIndexChanged.connect(self.selectAnomaly)
        # 3. Plot Button
        self.pushButton_3.setEnabled(False)
        self.pushButton_3.clicked.connect(self.plotAnomaly)

        # creating canvas objects for plots
        # live play
        self.canvas = MplCanvas(self, width=5, height=4, dpi=100)
        self.ui.verticalLayout.addWidget(self.canvas)
        self.background = None
        self.liveData = None
        # total graph
        self.canvas_2 = MplCanvas(self, width=5, height=4, dpi=100)
        self.ui.verticalLayout_2.addWidget(self.canvas_2)
        # total graph click handler
        self.canvas_2.fig.canvas.mpl_connect('button_press_event', self.mouseClick)
        self.background_2 = None
        self.mousePlayback = True

        # set backgrounds
        self.canvas.axes.set_facecolor(BG_GRAY)
        self.canvas_2.axes.set_facecolor(BG_BLACK)

        # initialize tick counts
        self.xtickCount = 10
        self.ytickCount = 8

        # load anomaly data
        # (currently just drawing randomly)
        self.typeArr = []               # list for crackle types
        self.typeArr.append([1, 2, 3])
        self.typeArr.append([2, 1, 3, 2])

        self.locArr = []                # list for crackle positions
        self.locArr.append([2367, 15000, 90000])
        self.locArr.append([5331, 27600, 52137, 81946])

        self.anomWidth = HIGHLIGHT_WIDTH
        self.spanArray = []

        self.scattersInTotal = []   # references to plotted scatters
        # (anomaly arrays will be loaded from pickle later)
        # self.data_c = pickle.load("")

        i = 0
        self.comboBox.addItem("--")
        for item in self.typeArr[self.patientNumber]:
            i += 1
            self.comboBox.addItem("Plot #{}".format(i))

        # initialize player for audio playback
        self.player = QMediaPlayer()
        self.player.setNotifyInterval(1)
        self.playbackTracker = None     # this is for total graph sweeper line
        self.playbackStarted = False
        self.prevPos = 0                # holder for previous call position in data shifting

        # load first channel audio
        self.radioButton.setChecked(True)

        # playback buttons
        self.pushButton.clicked.connect(self.playButton)
        self.pushButton_2.clicked.connect(self.stopButton)
        self.pushButton_2.setEnabled(False)

        # initialize worker for playback
        self.workerPlotUpdater = None
        self.workerStarted = False
        self.keepWorkerRunning = False

    def clearTracker(self):
        if self.playbackTracker is not None:
            try:
                self.playbackTracker.remove()
            except Exception as e:
                if type(e) == ValueError:
                    pass
                else:
                    print(type(e))
                    print(e)

    def clearLivePlot(self):
        self.liveData[0].set_ydata(np.zeros(self.length))

    def addSpans(self):
        for item in self.spanArray:
            try:
                item.remove()
            except Exception as e:
                print("error1: ", e)
                print(type(e))
            self.spanArray = []
        currentSample = int((self.player.position() / 9999) * SAMPLE_COUNT)
        for i in range(len(self.typeArr[self.patientNumber])):
            # full draw
            if currentSample - self.locArr[self.patientNumber][i] > self.anomWidth:
                # self.spanArray.append(
                tempRef = self.canvas.axes.axvspan(self.length - currentSample + self.locArr[self.patientNumber][i] -
                                                   self.anomWidth/2, self.length - currentSample +
                                                   self.locArr[self.patientNumber][i] + self.anomWidth/2,
                                                   facecolor=SCATTER_COLORS[self.typeArr[self.patientNumber][i]-1],
                                                   alpha=0.5)
                self.spanArray.append(tempRef)
                self.canvas.axes.draw_artist(tempRef)
            else:
                break

    def redrawLivePlot(self):
        try:
            self.canvas.restore_region(self.background)
            self.canvas.axes.draw_artist(self.liveData[0])
            self.addSpans()
            self.canvas.update()
            # self.canvas.flush_events()
        except Exception as e:
            if type(e) == TypeError:
                pass
            else:
                print(type(e))

    def redrawTotalPlot(self):
        try:
            self.canvas_2.restore_region(self.background_2)
            self.canvas_2.axes.draw_artist(self.playbackTracker)
            self.canvas_2.update()
            # self.canvas_2.flush_events()
        except Exception as e:
            if type(e) == TypeError:
                pass
            else:
                print(type(e))

    def mouseClick(self, event):
        # print('x: {} and y: {}'.format(event.xdata, event.ydata))
        if self.mousePlayback:
            self.clearTracker()
            try:
                player_pos = (event.xdata / SAMPLE_COUNT) * 9999
            except Exception as e:
                player_pos = 0
                if type(e) == TypeError:
                    pass
                else:
                    print(e)
                    print(type(e))
            self.player.setPosition(int(player_pos))
            self.playbackStarted = True
            if self.playbackTracker is not None:
                self.playbackTracker = self.canvas_2.axes.axvline(event.xdata, color="r", lw=0.9, alpha=0.5)
        else:
            self.clearTracker()
            if self.playbackTracker is not None:
                self.playbackTracker = self.canvas_2.axes.axvline(int(event.xdata), color="r", lw=0.9, alpha=0.5)
            # TODO: Add legend for clicked point

    def updateLivePlot(self):
        self.workerStarted = True
        while self.keepWorkerRunning:
            if self.playbackStarted:
                # update live plot
                currentSample = int((self.player.position() / 9999) * SAMPLE_COUNT)
                if currentSample != self.prevPos and currentSample > 0:
                    self.prevPos = currentSample
                    if currentSample < self.length:
                        newData = np.concatenate((np.zeros(self.length - currentSample), self.signal[0:currentSample]),
                                                 axis=0)
                    else:
                        newData = self.signal[currentSample-self.length:currentSample]
                    self.liveData[0].set_ydata(newData)
                    self.redrawLivePlot()

                # handle playback completion
                if self.player.position() == 9999:
                    self.pushButton.setText("Start")
                    self.pushButton_2.setEnabled(False)
                    self.groupBox_2.setEnabled(True)
                    self.groupBox_3.setEnabled(True)
                    self.player.stop()
                    self.playbackStarted = False
                    self.keepWorkerRunning = False
                    # self.workerPlotUpdater = None

                    if self.playbackTracker is not None:
                        self.clearTracker()
                        self.redrawTotalPlot()
                # sweep total plot while playing
                elif self.player.state() != 2:
                    # add vertical line on total graph as playback position tracker
                    self.clearTracker()
                    line_pos = (self.player.position() / 9999) * SAMPLE_COUNT
                    self.playbackTracker = self.canvas_2.axes.axvline(line_pos, color="r", lw=0.9, alpha=0.5)
                    self.redrawTotalPlot()
                # playing paused, update sweeper
                else:
                    self.clearTracker()
                    line_pos = (self.player.position() / 9999) * SAMPLE_COUNT
                    self.playbackTracker = self.canvas_2.axes.axvline(line_pos, color="r", lw=0.9, alpha=0.5)
                    self.redrawTotalPlot()
                    self.playbackStarted = False
                    # self.workerPlotUpdater = None
        self.workerPlotUpdater = None
        self.workerStarted = False

    def setChannel(self, value, x):
        # value: True if checked
        if value:
            self.channel = x
            if x == 1 and self.radioButton.isChecked():
                self.radioButton_2.setChecked(False)
                self.radioButton_3.setChecked(False)
                self.radioButton_4.setChecked(False)
            elif x == 2 and self.radioButton_2.isChecked():
                self.radioButton.setChecked(False)
                self.radioButton_3.setChecked(False)
                self.radioButton_4.setChecked(False)
            elif x == 3 and self.radioButton_3.isChecked():
                self.radioButton.setChecked(False)
                self.radioButton_2.setChecked(False)
                self.radioButton_4.setChecked(False)
            elif x == 4 and self.radioButton_4.isChecked():
                self.radioButton.setChecked(False)
                self.radioButton_2.setChecked(False)
                self.radioButton_3.setChecked(False)
            self.loadAudioFile()

    def updateBackground(self):
        # print("plot length:", self.length)
        # clear previous data
        self.canvas.axes.clear()
        # set empty data
        self.liveData = self.canvas.axes.plot(np.zeros(self.length), color='tab:cyan')

        # adjust limits
        ymin, ymax = self.canvas_2.axes.get_ylim()
        self.canvas.axes.set_ylim(ymin=ymin, ymax=ymax)
        self.canvas.axes.margins(x=0.01, y=0.03)

        # set how many tick labels to add
        self.canvas.axes.xaxis.set_major_locator(ticker.MultipleLocator(int(self.length / (self.xtickCount + 1))))
        y_step = (self.maximum - self.minimum) / (self.ytickCount + 1)
        y_step = round(y_step, 2)
        self.canvas.axes.yaxis.set_major_locator(ticker.MultipleLocator(y_step))

        # hide x-axis tick labels for live plot
        self.canvas.axes.xaxis.set_major_formatter(plt.NullFormatter())

        # add grids
        self.canvas.axes.yaxis.grid(True, linestyle='--')
        self.canvas.axes.xaxis.grid(True, linestyle='--')

        self.canvas.draw()
        self.liveData[0].remove()
        self.canvas.draw()
        self.background = self.canvas.copy_from_bbox(self.canvas.axes.bbox)

    def zoomSlider(self, value):
        self.lineEdit.setText(str(value))
        self.zoomRate = value
        self.length = int(SAMPLE_COUNT / self.zoomRate)

    def sliderReleaseHandler(self):
        self.playbackStarted = False
        self.updateBackground()
        currentSample = int((self.player.position() / 9999) * SAMPLE_COUNT)
        if currentSample >= self.length:
            self.liveData = self.canvas.axes.plot(self.signal[currentSample-self.length:currentSample],
                                                  color='tab:cyan')
        else:
            newData = np.concatenate((np.zeros(self.length - currentSample), self.signal[0:currentSample]), axis=0)
            self.liveData = self.canvas.axes.plot(newData, color='tab:cyan')
        self.anomWidth = HIGHLIGHT_WIDTH / self.zoomRate
        self.redrawLivePlot()

    def zoomEdit(self):
        if not self.lineEdit.text().isdigit():
            self.lineEdit.setText(str(self.horizontalSlider.value()))
            return -1
        value = int(self.lineEdit.text())
        if 1 <= value <= MAX_ZOOM:
            self.zoomRate = value
            self.horizontalSlider.setValue(value)
        elif value < 1:
            self.zoomRate = 1
            self.horizontalSlider.setValue(1)
            self.lineEdit.setText("1")
        else:
            self.zoomRate = MAX_ZOOM
            self.horizontalSlider.setValue(MAX_ZOOM)
            self.lineEdit.setText(str(MAX_ZOOM))
        self.length = int(SAMPLE_COUNT / self.zoomRate)
        # change display if paused
        self.sliderReleaseHandler()

    def updatePause(self):
        if self.checkBox.isChecked():
            self.mypause = 1
        else:
            self.mypause = 0

    def updateNewWindowPlotting(self):
        if self.checkBox_2.isChecked():
            self.plotInNewWindow = 1
        else:
            self.plotInNewWindow = 0

    def selectAnomaly(self, value):
        self.selectedAnomaly = value

    def plotAnomaly(self):
        if self.selectedAnomaly == -1:
            PopUp("Information", "Please select an anomaly first.")
            return -1

        if self.plotInNewWindow:
            # plot in new window
            print("will be added later")
        else:
            # plot over live plot
            # maybe include tabbing later
            print("will be added later")

    def loadAudioFile(self):
        # TODO: clear previous data each time a new file is loaded
        fileName = REL_PATH + str(self.patientNumber) + FILE_LIST[self.channel-1]
        url = QUrl.fromLocalFile(QFileInfo(fileName).absoluteFilePath())
        self.player.setMedia(QMediaContent(url))        # load file to player
        # try reading the file
        try:
            raw = wave.open(fileName)
        except Exception as e:
            print(e)
            print(type(e))
            raw = 0
            PopUp("Error!", "Unable to load the file.")

        signal = raw.readframes(-1)                     # read all the frames
        signal = np.frombuffer(signal, dtype="int16")   # convert bytes to int

        # find max value to normalize
        self.maximum = np.amax(signal)
        self.minimum = np.amin(signal)
        if abs(self.minimum) > self.maximum:
            largest = abs(self.minimum)
        else:
            largest = self.maximum

        if largest == 0:
            PopUp("Error!", "Invalid data!")
            return -1

        # normalize
        self.signal = signal / largest
        self.maximum /= largest
        self.minimum /= largest
        self.updateTotalPlot()  # load file to total plot

    def updateTotalPlot(self):
        self.canvas_2.axes.cla()        # clear previous content
        # TODO: Clear also live plot
        # TODO: Set also live plot y-axis

        # resolution
        print("Total plot size:", self.canvas_2.fig.get_size_inches()*self.canvas_2.fig.dpi)  # total white area

        # set space between axes and figure (w.r.t. initial size)
        self.canvas_2.fig.subplots_adjust(left=0.06, right=0.98, top=0.98, bottom=0.13)

        # set how many tick labels to add
        self.canvas_2.axes.xaxis.set_major_locator(ticker.MultipleLocator(int(SAMPLE_COUNT/(self.xtickCount + 1))))
        y_step = (self.maximum - self.minimum) / (self.ytickCount + 1)
        y_step = round(y_step, 2)
        self.canvas_2.axes.yaxis.set_major_locator(ticker.MultipleLocator(y_step))

        # set the space between tick label and y-axis
        self.canvas_2.axes.tick_params(axis="y", which="major", pad=1)

        # set space between data and plot limits
        self.canvas_2.axes.margins(x=0.01, y=0.03)

        # add grids
        self.canvas_2.axes.yaxis.grid(True, linestyle='--')
        self.canvas_2.axes.xaxis.grid(True, linestyle='--')

        # plot_refs_2 =
        self.canvas_2.axes.plot(self.signal, color=(0, 1, 0.29))
        # clear previous scatter
        for j in range(len(self.scattersInTotal)):
            self.scattersInTotal[j].remove()
        self.scattersInTotal = []

        # scatter anomaly data
        # TODO: is the scatter supposed to be shown before playback?
        for i in range(len(self.typeArr[self.patientNumber])):
            tempRef = self.canvas_2.axes.scatter(self.locArr[self.patientNumber][i],
                                                 self.signal[self.locArr[self.patientNumber][i]],
                                                 color=SCATTER_COLORS[self.typeArr[self.patientNumber][i]-1],
                                                 zorder=2, alpha=0.7)
            self.scattersInTotal.append(tempRef)

        # draw
        self.canvas_2.draw()

        # start live plot
        self.startLivePlot()

    def startLivePlot(self):
        self.canvas.axes.cla()  # clear previous content

        # hide x-axis tick labels for live plot
        self.canvas.axes.xaxis.set_major_formatter(plt.NullFormatter())

        # set space between axes and live plot figure (w.r.t. initial size)
        self.canvas.fig.subplots_adjust(left=0.06, right=0.98, top=0.98, bottom=0.13)

        # set how many tick labels to add
        # TODO: Add this section to updateLivePlot
        self.canvas.axes.xaxis.set_major_locator(ticker.MultipleLocator(int(self.length / (self.xtickCount + 1))))
        y_step = (self.maximum - self.minimum) / (self.ytickCount + 1)
        y_step = round(y_step, 2)
        self.canvas.axes.yaxis.set_major_locator(ticker.MultipleLocator(y_step))

        # set axis limits
        # xmin, xmax = self.canvas_2.axes.get_xlim()
        # self.canvas.axes.set_xlim(xmin=xmin, xmax=xmax)
        ymin, ymax = self.canvas_2.axes.get_ylim()
        self.canvas.axes.set_ylim(ymin=ymin, ymax=ymax)

        # set the space between tick label and y-axis
        self.canvas.axes.tick_params(axis="y", which="major", pad=1)

        # set space between data and plot limits
        self.canvas.axes.margins(x=0.01, y=0.03)

        # add grids
        self.canvas.axes.yaxis.grid(True, linestyle='--')
        self.canvas.axes.xaxis.grid(True, linestyle='--')

        # set empty data
        self.liveData = self.canvas.axes.plot(np.zeros(self.length), color='tab:cyan')

        # draw
        self.canvas.draw()

    def playButton(self):
        # print("play button is called")
        # deny inputs until everything is executed
        self.pushButton.setEnabled(False)
        if self.player.state() == 0 or self.player.state() == 2:
            self.pushButton.setText("Pause")
            self.pushButton_2.setEnabled(True)
            # disable channel and zoom settings
            self.groupBox_2.setEnabled(False)
            self.groupBox_3.setEnabled(False)

            if self.player.state() == 0 and self.background is None:
                self.liveData[0].remove()
                self.canvas.draw()
                self.background = self.canvas.copy_from_bbox(self.canvas.axes.bbox)
                self.clearLivePlot()
            if self.player.state() == 0 and self.background_2 is None:
                self.clearTracker()
                self.canvas_2.draw()
                self.background_2 = self.canvas_2.copy_from_bbox(self.canvas_2.axes.bbox)

            self.keepWorkerRunning = True
            self.playbackStarted = True

            # start a thread for plot updates
            if self.workerPlotUpdater is None:
                # self.threadpool.clear()  # clear previous dead threads
                self.workerPlotUpdater = Worker(self.updateLivePlot)
                self.threadpool.start(self.workerPlotUpdater)
            # wait for worker
            while not self.workerStarted:
                time.sleep(0.1)
            self.player.play()

        else:
            self.pushButton.setText("Continue")
            self.player.pause()
            self.groupBox_3.setEnabled(True)
        # allow new inputs once everything is executed
        self.pushButton.setEnabled(True)

    def stopButton(self):
        self.player.stop()
        self.playbackStarted = False
        self.keepWorkerRunning = False
        self.workerPlotUpdater = None
        self.pushButton.setText("Start")
        self.pushButton_2.setEnabled(False)
        self.groupBox_2.setEnabled(True)
        self.groupBox_3.setEnabled(True)
        if self.playbackTracker is not None:
            self.clearTracker()
            self.redrawTotalPlot()
        self.clearLivePlot()
        self.redrawLivePlot()

    # override resize event to adjust plot sizes
    def resizeEvent(self, event):
        # print("will be added later")
        # TODO: Change space allocated for tick labels, space between figure and axes
        # TODO: Change # of tick labels
        # TODO: Do the same with live plot
        # self.canvas_2.fig.subplots_adjust(left=0.06, right=0.995, top=1, bottom=0.1)
        # self.tickCount = size_related_calc
        # self.canvas_2.axes.xaxis.set_major_locator(ticker.MultipleLocator(int(SAMPLE_COUNT / (self.xtickCount + 1))))
        # y_step = (self.maximum - self.minimum) / (self.ytickCount + 1)
        # y_step = round(y_step, 2)
        # self.canvas_2.axes.yaxis.set_major_locator(ticker.MultipleLocator(y_step))
        self.keepWorkerRunning = False

    # override close event to restore first window
    def closeEvent(self, event):
        self.stopButton()
        self.close()
        self.patientWindow.show()
        if not self.patientWindow.lineEdit.isEnabled():
            self.patientWindow.lineEdit.setEnabled(True)
            self.patientWindow.lineEdit.setText("")


app = QtWidgets.QApplication(sys.argv)
mainWindow = StartPage()
mainWindow.show()
sys.exit(app.exec_())
