"""Disposable native fixture; it owns only its unsaved window and text buffer."""

import os


def main():
    import AppKit as A

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((100, 150), (600, 400)),
        A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
        A.NSBackingStoreBuffered,
        False,
    )
    window.setTitle_(f"Agent Control Native Test {os.getpid()}")
    editor = A.NSTextView.alloc().initWithFrame_(((20, 20), (560, 350)))
    editor.setString_("Agent Control fixture")
    editor.setRichText_(False)
    window.contentView().addSubview_(editor)
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(editor)
    app.activateIgnoringOtherApps_(True)
    print(os.getpid(), flush=True)
    app.run()


if __name__ == "__main__":
    main()
