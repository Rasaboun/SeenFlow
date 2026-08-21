import UIKit

final class FixtureView: UIView {
    private var tapped = false
    private let welcomeInitiallyVisible = ProcessInfo.processInfo.arguments.contains {
        $0.contains("welcomeInitiallyVisible")
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .white
        isAccessibilityElement = false
        accessibilityElementsHidden = true
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is unsupported")
    }

    private var buttonRect: CGRect {
        CGRect(x: bounds.midX - 150, y: bounds.midY - 45, width: 300, height: 90)
    }

    override func draw(_ rect: CGRect) {
        if welcomeInitiallyVisible || tapped {
            draw("Welcome", centerY: bounds.midY - 170, color: .black, size: 52)
        }
        guard !tapped else {
            draw("Tapped", centerY: bounds.midY, color: .black, size: 44)
            return
        }
        UIColor.systemBlue.setFill()
        UIBezierPath(roundedRect: buttonRect, cornerRadius: 22).fill()
        draw("Continue", centerY: buttonRect.midY, color: .white, size: 44)
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let point = touches.first?.location(in: self), buttonRect.contains(point) else { return }
        tapped = true
        setNeedsDisplay()
    }

    private func draw(_ text: String, centerY: CGFloat, color: UIColor, size: CGFloat) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: size, weight: .bold),
            .foregroundColor: color,
        ]
        let measured = text.size(withAttributes: attributes)
        text.draw(
            at: CGPoint(x: bounds.midX - measured.width / 2, y: centerY - measured.height / 2),
            withAttributes: attributes
        )
    }
}

final class AppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let window = UIWindow(frame: UIScreen.main.bounds)
        let controller = UIViewController()
        controller.view = FixtureView(frame: window.bounds)
        window.rootViewController = controller
        window.makeKeyAndVisible()
        self.window = window
        return true
    }
}

UIApplicationMain(CommandLine.argc, CommandLine.unsafeArgv, nil, NSStringFromClass(AppDelegate.self))
