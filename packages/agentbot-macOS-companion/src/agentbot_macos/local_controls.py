"""Menu-bar consent and physical takeover on the native main run loop."""


def run_menu(companion, loop):
    import asyncio

    import AppKit as A
    import Quartz as Q
    from Foundation import NSObject, NSTimer

    from agentbot_macos.capture import windows
    from agentbot_macos.text_input import EVENT_TAG

    class Target(NSObject):
        def sharing_(self, sender):
            companion.state.change(sharing=not companion.state.sharing, armed=False)
            asyncio.run_coroutine_threadsafe(companion.worker.stop(), loop)

        def armed_(self, sender):
            if companion.hello().ready and companion.state.sharing and monitor:
                companion.state.change(armed=not companion.state.armed)
                if not companion.state.armed:
                    asyncio.run_coroutine_threadsafe(companion.local_stop(), loop)

        def scope_(self, sender):
            companion.state.change(
                scope="window" if companion.state.scope == "display" else "display", armed=False
            )
            asyncio.run_coroutine_threadsafe(companion.worker.stop(), loop)

        def stop_(self, sender):
            companion.state.stop()
            asyncio.run_coroutine_threadsafe(companion.local_stop(), loop)

        def select_(self, sender):
            companion.state.change(
                window=str(sender.representedObject()), scope="window", armed=False
            )
            asyncio.run_coroutine_threadsafe(companion.worker.stop(), loop)

        def refresh_(self, sender):
            selection.removeAllItems()
            if companion.hello().screen_recording:
                for window in windows():
                    item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        window["name"], "select:", ""
                    )
                    item.setRepresentedObject_(window["id"])
                    item.setTarget_(self)
                    selection.addItem_(item)

        def tick_(self, sender):
            share.setState_(int(companion.state.sharing))
            arm.setState_(int(companion.state.armed))
            scope.setState_(int(companion.state.scope == "display"))
            status.setTitle_((companion.status + " · " + companion.hello().reason)[:140])

        def quit_(self, sender):
            companion.state.stop("Companion closed")
            companion.running = False
            asyncio.run_coroutine_threadsafe(companion.local_stop(), loop).result(timeout=5)
            app.terminate_(None)

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    target = Target.alloc().init()
    menu = A.NSMenu.alloc().init()

    def item(title, action=None):
        entry = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            entry.setTarget_(target)
        menu.addItem_(entry)
        return entry

    status = item("Mac companion")
    share = item("Share screen", "sharing:")
    arm = item("Allow agent control", "armed:")
    scope = item("Share whole primary display", "scope:")
    selection = A.NSMenu.alloc().init()
    choose = item("Selected window")
    choose.setSubmenu_(selection)
    item("Refresh available windows", "refresh:")
    item("Stop agent", "stop:")
    item("Quit companion", "quit:")
    bar = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
    bar.button().setTitle_("Agent Control")
    bar.setMenu_(menu)
    target.refresh_(None)
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1, target, "tick:", None, True
    )

    def physical(event):
        cg = event.CGEvent()
        if cg is None:
            return
        pid = Q.CGEventGetIntegerValueField(cg, Q.kCGEventSourceUnixProcessID)
        tag = Q.CGEventGetIntegerValueField(cg, Q.kCGEventSourceUserData)
        # Physical HID events have no injecting process. Synthetic events retain
        # a source pid; literal Unicode additionally carries our event tag.
        if pid == 0 and tag != EVENT_TAG and companion.state.armed and companion.automating:
            companion.state.stop("Physical input; agent paused")
            asyncio.run_coroutine_threadsafe(
                companion.local_stop("Physical input; agent paused"), loop
            )

    mask = (
        A.NSEventMaskKeyDown
        | A.NSEventMaskLeftMouseDown
        | A.NSEventMaskRightMouseDown
        | A.NSEventMaskMouseMoved
        | A.NSEventMaskScrollWheel
    )
    monitor = A.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, physical)

    def local_event(event):
        physical(event)
        return event

    local_monitor = A.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, local_event)
    try:
        app.run()
    finally:
        timer.invalidate()
        if monitor:
            A.NSEvent.removeMonitor_(monitor)
        if local_monitor:
            A.NSEvent.removeMonitor_(local_monitor)
