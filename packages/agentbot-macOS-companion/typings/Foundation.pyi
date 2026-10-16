"""Objective-C class selectors are supplied dynamically by PyObjC."""

from typing import Any, Self

class NSObject:
    @classmethod
    def alloc(cls) -> Self: ...
    def init(self) -> Self: ...

NSDate: Any
NSRunLoop: Any
NSTimer: Any
NSData: Any
