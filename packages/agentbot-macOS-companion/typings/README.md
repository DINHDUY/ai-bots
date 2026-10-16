Partial type stubs for the optional native boundary. PyObjC exports Objective-C
classes and selectors at runtime, so opaque CF handles and Objective-C objects
are typed as Any; C function signatures and portable controller interfaces retain
types. The declared PyObjC names were checked against installed PyObjC 12.2.2.
Galaxy stubs describe only the pinned ExecutionResult bridge seam, exercised by
scripts/macos_taskstar_probe.py. These files are not runtime implementations.
The workspace deliberately has no native module sources; the Mac execution
environment suppresses only missing-source diagnostics when a stub is present.
