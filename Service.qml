import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root
  property var shell: null
  property var manifest: null
  property bool tabletMode: false
  property bool rotationLocked: false
  property bool busy: false
  property string error: ""
  property string orientation: "undefined"
  property int desiredTransform: 0
  readonly property string directory: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")
  property string action: ""
  property int appliedTransform: -1
  property real keyboardWidth: 1040
  property real keyboardHeight: 348

  function run(actionName, argument) {
    if (busy) return false
    error = ""
    action = actionName
    platform.result = null
    busy = true
    var args = ["python3", directory + "/platform.py", actionName]
    if (argument !== undefined) args.push(String(argument))
    platform.exec(args)
    return true
  }
  function setTabletMode(enabled) {
    if (busy || (enabled && tabletMode)) return
    run(enabled ? "begin" : "end")
  }
  function toggleTabletMode() { setTabletMode(!tabletMode) }
  function toggleRotationLock() { rotationLocked = !rotationLocked; if (!rotationLocked) rotatePending() }
  function rotatePending() {
    if (tabletMode && !rotationLocked && !busy && orientation !== "undefined" && appliedTransform !== desiredTransform)
      run("rotate", desiredTransform)
  }
  function toggleKeyboard() {
    if (keyboardLoader.active) keyboardLoader.active = false
    else keyboardLoader.active = true
  }
  function handleSensor(line) {
    try {
      var packet = JSON.parse(line)
      if (packet.orientation) {
        orientation = packet.orientation
        var mapping = {normal:0, "bottom-up":2, "left-up":1, "right-up":3}
        if (mapping[orientation] !== undefined) {
          desiredTransform = mapping[orientation]
          rotationDelay.restart()
        }
      }
    } catch (e) { error = "Invalid sensor response: " + e }
  }
  Timer { id: rotationDelay; interval: 250; onTriggered: root.rotatePending() }
  Process {
    id: sensor
    command: ["sh", root.directory + "/sensor-backend.sh", "--watch"]
    running: root.tabletMode && !root.rotationLocked
    stdinEnabled: true
    stdout: SplitParser { onRead: function(line) { root.handleSensor(line) } }
    stderr: SplitParser { onRead: function(line) { root.error = line } }
    onExited: function(code, status) {
      if (root.tabletMode && !root.rotationLocked && (code !== 0 || status !== 0)) {
        root.rotationLocked = true
        if (!root.error) root.error = "Accelerometer unavailable; rotation is locked. The keyboard still works."
      }
    }
  }
  Process {
    id: platform
    property var result: null
    stdout: SplitParser { onRead: function(line) { try { platform.result = JSON.parse(line) } catch(e) { root.error = line } } }
    stderr: SplitParser { onRead: function(line) { root.error = line } }
    onExited: function(code, status) {
      root.busy = false
      if (code !== 0 || status !== 0) {
        if (!root.error) root.error = "Tablet platform operation failed."
        if (root.action === "rotate") {
          root.tabletMode = false
          root.appliedTransform = -1
        }
        return
      }
      if (root.action === "begin") {
        root.tabletMode = true
        root.appliedTransform = -1
        keyboardLoader.active = true
      } else if (root.action === "end") {
        root.tabletMode = false
        keyboardLoader.active = false
        root.appliedTransform = -1
      }
      if (root.action === "rotate" && platform.result)
        root.appliedTransform = platform.result.transform
      if (root.tabletMode && !root.rotationLocked && root.appliedTransform !== root.desiredTransform)
        rotationDelay.restart()
    }
  }
  Loader {
    id: keyboardLoader
    active: false
    source: "Keyboard.qml"
    onLoaded: {
      item.shell = {hide: function(id) { keyboardLoader.active = false }}
      item.manifest = root.manifest
      item.tabletService = root
      item.keyboardWidth = root.keyboardWidth
      item.keyboardHeight = root.keyboardHeight
      item.resized.connect(function(width, height) {
        root.keyboardWidth = width
        root.keyboardHeight = height
      })
      item.open("{}")
    }
  }
  IpcHandler {
    target: "omarkyy.tablet"
    function keyboard(): void { root.toggleKeyboard() }
    function tablet(): void { root.toggleTabletMode() }
    function rotationLock(): void { root.toggleRotationLock() }
    function off(): void { root.setTabletMode(false) }
    function status(): string { return JSON.stringify({tabletMode:root.tabletMode,rotationLocked:root.rotationLocked,orientation:root.orientation,busy:root.busy,error:root.error}) }
  }
  // Recover this plugin's own captured desktop state after an interrupted
  // shell. No journal means no monitor/device changes.
  Component.onCompleted: root.run("end")
  Component.onDestruction: {
    if (root.tabletMode) Quickshell.execDetached(["python3", root.directory + "/platform.py", "end"])
  }
}
