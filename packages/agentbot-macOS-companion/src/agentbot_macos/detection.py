"""Local OCR candidates; candidate text is untrusted and is never an AX identity."""

import base64


def detect(observation: dict, query: str = "", *, ocr: bool = True) -> list[dict]:
    if not isinstance(query, str) or len(query) > 300:
        raise ValueError("UI query is too long")
    records = list(observation["controls"])
    # OCR cannot reliably redact secure input. Only AX-known nonsecure scopes
    # are eligible; the native observer withholds images containing secure fields.
    if ocr and observation.get("ocr_allowed"):
        import Foundation
        import Vision

        image = base64.b64decode(observation["capture"]["image"], validate=True)
        data = Foundation.NSData.dataWithBytes_length_(image, len(image))
        request = Vision.VNRecognizeTextRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
        success, _ = handler.performRequests_error_([request], None)
        if success:
            for index, result in enumerate(request.results() or []):
                if index >= 100:
                    break
                candidates = result.topCandidates_(1)
                if not candidates:
                    continue
                candidate = candidates[0]
                box = result.boundingBox()
                records.append(
                    {
                        "id": f"ocr:{index}",
                        "source": "ocr",
                        "label": str(candidate.string())[:300],
                        "confidence": float(candidate.confidence()),
                        "normalized_bounds": [
                            box.origin.x,
                            1 - box.origin.y - box.size.height,
                            box.size.width,
                            box.size.height,
                        ],
                        "interactive": False,
                    }
                )
    return [r for r in records if query.casefold() in r.get("label", "").casefold()][:300]
