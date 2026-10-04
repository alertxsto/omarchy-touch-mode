import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "omarkyy.tablet"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: "Left: keyboard · Right: tablet mode · Middle: rotation lock"
    // Draw the keyboard instead of relying on an optional icon-font glyph.
    iconComponent: Component {
      Item {
        Rectangle {
          anchors.centerIn: parent
          width: 20; height: 14
          radius: 2
          color: "transparent"
          border.width: 1
          border.color: button.foreground
          Grid {
            x: 3; y: 3
            columns: 5; spacing: 1
            Repeater {
              model: 10
              delegate: Rectangle { width: 2; height: 2; color: button.foreground }
            }
          }
          Rectangle { x: 5; y: 10; width: 10; height: 1; color: button.foreground }
        }
      }
    }
    onPressed: function(mouseButton) {
      var action = mouseButton === Qt.RightButton ? "tablet" : mouseButton === Qt.MiddleButton ? "rotationLock" : "keyboard"
      Quickshell.execDetached(["omarchy-shell", "omarkyy.tablet", action])
    }
  }
}
