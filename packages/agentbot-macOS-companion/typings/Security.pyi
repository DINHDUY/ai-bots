"""Partial Keychain signatures; security attributes are bridged CF objects."""

from typing import Any

kSecClass: Any
kSecClassGenericPassword: Any
kSecAttrService: Any
kSecAttrAccount: Any
kSecReturnData: Any
kSecMatchLimit: Any
kSecMatchLimitOne: Any
kSecValueData: Any
errSecItemNotFound: int

def SecItemCopyMatching(query: dict, result: None) -> tuple[int, Any]: ...
def SecItemUpdate(query: dict, attributes: dict) -> int: ...
def SecItemAdd(attributes: dict, result: None) -> tuple[int, Any]: ...
def SecItemDelete(query: dict) -> int: ...
