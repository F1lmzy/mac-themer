// macthemer-wallpaper — set, read and re-assert the desktop picture.
//
// mac-themer builds this rather than shelling out to another project's helper,
// because the themer has to be installable on its own. NSWorkspace is used
// directly because it is the only path that reliably sets a per-screen picture
// on macOS 14 and later: System Events wallpaper scripting intermittently
// returns missing value there and silently keeps the old image, which is a
// failure you cannot see until you notice the wrong wallpaper.
//
//   macthemer-wallpaper set <path>    every screen
//   macthemer-wallpaper get           one line per screen, in arrangement order
//   macthemer-wallpaper resync <path> re-assert it on screens showing something else
//
// resync exists because macOS keeps the desktop picture per display: a screen
// unplugged during a theme change comes back with the picture it had, so the
// machine can be left showing two themes at once until something re-applies.
import AppKit
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("macthemer-wallpaper: \(message)\n".utf8))
    exit(1)
}

func usage() -> Never {
    FileHandle.standardError.write(Data("""
    usage: macthemer-wallpaper set <path>
           macthemer-wallpaper get
           macthemer-wallpaper resync <path>

    """.utf8))
    exit(2)
}

func requireExisting(_ path: String) -> URL {
    let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath).standardizedFileURL
    guard FileManager.default.fileExists(atPath: url.path) else {
        fail("no such file: \(url.path)")
    }
    return url
}

// Standardised so two spellings of one file compare equal: the remembered link,
// the pack-relative path and an absolute path all reach the same inode.
func picturePath(of screen: NSScreen) -> String? {
    NSWorkspace.shared.desktopImageURL(for: screen)?.standardizedFileURL.path
}

func apply(_ url: URL, to screen: NSScreen) -> String? {
    do {
        try NSWorkspace.shared.setDesktopImageURL(url, for: screen, options: [:])
        return nil
    } catch {
        return error.localizedDescription
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
switch arguments.first {
case "set":
    guard arguments.count == 2 else { usage() }
    let url = requireExisting(arguments[1])
    var failures: [String] = []
    for screen in NSScreen.screens {
        if let problem = apply(url, to: screen) {
            failures.append("\(screen.localizedName): \(problem)")
        }
    }
    guard failures.isEmpty else { fail(failures.joined(separator: "; ")) }
    print("wallpaper: \(url.lastPathComponent) on \(NSScreen.screens.count) screen(s)")

case "get":
    // Arrangement order, which is the order a user reads their displays in.
    for (index, screen) in NSScreen.screens.enumerated() {
        print("\(index)\t\(screen.localizedName)\t\(picturePath(of: screen) ?? "-")")
    }

case "resync":
    guard arguments.count == 2 else { usage() }
    let wanted = requireExisting(arguments[1])
    var changed = 0
    var failures: [String] = []
    for screen in NSScreen.screens where picturePath(of: screen) != wanted.path {
        if let problem = apply(wanted, to: screen) {
            failures.append("\(screen.localizedName): \(problem)")
        } else {
            changed += 1
        }
    }
    guard failures.isEmpty else { fail(failures.joined(separator: "; ")) }
    print("wallpaper resync: \(changed) of \(NSScreen.screens.count) screen(s) reset to \(wanted.lastPathComponent)")

default:
    usage()
}
