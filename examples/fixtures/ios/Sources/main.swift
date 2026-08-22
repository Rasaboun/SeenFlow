import UIKit

final class FixtureView: UIView {
    private var tapped = false
    private var longPressed = false
    private let longPressMode = ProcessInfo.processInfo.arguments.contains {
        $0.contains("longPressMode")
    }
    private let spatialMode = ProcessInfo.processInfo.arguments.contains {
        $0.contains("spatialMode")
    }
    private let welcomeInitiallyVisible = ProcessInfo.processInfo.arguments.contains {
        $0.contains("welcomeInitiallyVisible")
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .white
        isAccessibilityElement = false
        accessibilityElementsHidden = true
        if longPressMode {
            let recognizer = UILongPressGestureRecognizer(target: self, action: #selector(handleLongPress(_:)))
            recognizer.minimumPressDuration = 0.5
            addGestureRecognizer(recognizer)
        }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) is unsupported")
    }

    private var buttonRect: CGRect {
        CGRect(x: bounds.midX - 150, y: bounds.midY - 45, width: 300, height: 90)
    }

    private func spatialButton(centerY: CGFloat) -> CGRect {
        CGRect(x: bounds.width * 0.75 - 70, y: centerY - 40, width: 140, height: 80)
    }

    override func draw(_ rect: CGRect) {
        if spatialMode {
            if tapped {
                draw("Edit recipe", centerY: bounds.midY, color: .black, size: 44)
                return
            }
            let firstRow = bounds.midY - 130
            let secondRow = bounds.midY + 130
            draw("Chicken Curry", centerY: firstRow, color: .black, size: 26, centerX: bounds.width * 0.32)
            draw("Edit", centerY: firstRow, color: .systemBlue, size: 26, centerX: bounds.width * 0.75)
            draw("Pasta", centerY: secondRow, color: .black, size: 26, centerX: bounds.width * 0.32)
            draw("Edit", centerY: secondRow, color: .systemBlue, size: 26, centerX: bounds.width * 0.75)
            return
        }
        if longPressMode {
            draw(longPressed ? "Actions" : "Press and hold", centerY: bounds.midY, color: .black, size: 52)
            return
        }
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
        if spatialMode {
            guard let point = touches.first?.location(in: self) else { return }
            guard spatialButton(centerY: bounds.midY - 130).contains(point) else { return }
            tapped = true
            setNeedsDisplay()
            return
        }
        guard !longPressMode else { return }
        guard let point = touches.first?.location(in: self), buttonRect.contains(point) else { return }
        tapped = true
        setNeedsDisplay()
    }

    @objc private func handleLongPress(_ recognizer: UILongPressGestureRecognizer) {
        guard recognizer.state == .began else { return }
        longPressed = true
        setNeedsDisplay()
    }

    private func draw(
        _ text: String,
        centerY: CGFloat,
        color: UIColor,
        size: CGFloat,
        centerX: CGFloat? = nil
    ) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: size, weight: .bold),
            .foregroundColor: color,
        ]
        let measured = text.size(withAttributes: attributes)
        text.draw(
            at: CGPoint(x: (centerX ?? bounds.midX) - measured.width / 2, y: centerY - measured.height / 2),
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
