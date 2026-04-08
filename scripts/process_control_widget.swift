import AppKit
import Foundation
import WebKit

private let dashboardURL = URL(string: "http://127.0.0.1:8765/")!
private let autosaveName = "RemoteControlWidgetWindow"

final class WidgetAppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSPanel!
    private var webView: WKWebView!
    private var reloadTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        buildWindow()
        loadDashboard()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        reloadTimer?.invalidate()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showFallback(message: error.localizedDescription)
    }

    func webView(
        _ webView: WKWebView,
        didFailProvisionalNavigation navigation: WKNavigation!,
        withError error: Error
    ) {
        showFallback(message: error.localizedDescription)
    }

    private func buildWindow() {
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let width: CGFloat = 460
        let height: CGFloat = min(860, screen.height - 80)
        let frame = NSRect(
            x: screen.maxX - width - 24,
            y: screen.maxY - height - 24,
            width: width,
            height: height
        )

        let panel = NSPanel(
            contentRect: frame,
            styleMask: [.titled, .closable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.title = "Remote Widget"
        panel.titlebarAppearsTransparent = false
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .moveToActiveSpace]
        panel.isMovableByWindowBackground = false
        panel.hidesOnDeactivate = false
        panel.setFrameAutosaveName(autosaveName)
        panel.minSize = NSSize(width: 380, height: 520)

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()

        let webView = WKWebView(frame: panel.contentView?.bounds ?? .zero, configuration: config)
        webView.navigationDelegate = self
        webView.autoresizingMask = [.width, .height]
        webView.setValue(false, forKey: "drawsBackground")

        panel.contentView = webView

        self.window = panel
        self.webView = webView
    }

    private func loadDashboard() {
        webView.load(URLRequest(url: dashboardURL, cachePolicy: .reloadIgnoringLocalCacheData))
    }

    private func showFallback(message: String) {
        let escapedMessage = escapeHTML(message)
        let html = """
        <!doctype html>
        <html lang="ko">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body {
              margin: 0;
              font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
              background: linear-gradient(180deg, #f5eee5 0%, #eadfcf 100%);
              color: #2a241f;
              display: grid;
              min-height: 100vh;
              place-items: center;
            }
            .card {
              width: min(360px, calc(100vw - 32px));
              background: rgba(255, 251, 246, 0.92);
              border-radius: 22px;
              padding: 24px;
              box-shadow: 0 18px 40px rgba(60, 45, 25, 0.14);
            }
            h1 {
              margin: 0 0 8px;
              font-size: 22px;
            }
            p {
              margin: 0 0 18px;
              line-height: 1.5;
              color: #655c53;
            }
            .detail {
              background: #f3ede4;
              border-radius: 14px;
              padding: 12px;
              font-size: 13px;
              color: #4e463e;
              white-space: pre-wrap;
              word-break: break-word;
            }
            .actions {
              margin-top: 16px;
              display: flex;
              gap: 10px;
              flex-wrap: wrap;
            }
            button, a {
              border: 0;
              border-radius: 12px;
              padding: 10px 14px;
              font-size: 13px;
              font-weight: 700;
              text-decoration: none;
              cursor: pointer;
              display: inline-flex;
              align-items: center;
              justify-content: center;
            }
            button {
              background: #1f7a49;
              color: white;
            }
            a {
              background: #e6dccf;
              color: #2f2a25;
            }
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Remote Widget</h1>
            <p>제어 서버에 아직 연결되지 않았습니다. 서버를 시작한 뒤 다시 연결할 수 있습니다.</p>
            <div class="detail">\(escapedMessage)</div>
            <div class="actions">
              <button onclick="window.location.href='\(dashboardURL.absoluteString)'">다시 시도</button>
              <a href="\(dashboardURL.absoluteString)">브라우저로 열기</a>
            </div>
          </div>
        </body>
        </html>
        """
        webView.loadHTMLString(html, baseURL: nil)

        reloadTimer?.invalidate()
        reloadTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { [weak self] _ in
            self?.loadDashboard()
        }
    }

    private func escapeHTML(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}

let app = NSApplication.shared
let delegate = WidgetAppDelegate()
app.delegate = delegate
app.run()
