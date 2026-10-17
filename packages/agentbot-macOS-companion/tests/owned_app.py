"""Disposable native fixture; it owns only its unsaved window and text buffer."""

import os
import sys


def main():
    import AppKit as A

    labels = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        ((100, 150), (600, 400)),
        A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
        A.NSBackingStoreBuffered,
        False,
    )
    window.setTitle_(f"Agent Control Native Test {os.getpid()}")
    editor_frame = ((20, 300), (560, 70)) if labels else ((20, 20), (560, 350))
    editor = A.NSTextView.alloc().initWithFrame_(editor_frame)
    editor.setString_("Agent Control fixture")
    editor.setRichText_(False)
    window.contentView().addSubview_(editor)
    for index in range(labels):
        label = A.NSTextField.labelWithString_(f"Fixture {index}")
        label.setFrame_(((index % 20 * 28, index // 20 * 16), (28, 16)))
        window.contentView().addSubview_(label)
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(editor)
    app.activateIgnoringOtherApps_(True)
    print(os.getpid(), flush=True)
    app.run()


if __name__ == "__main__":
    main()
