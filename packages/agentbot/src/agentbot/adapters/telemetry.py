"""Per-provider-call metrics, outside the SDK's tool invocation loop."""

from time import perf_counter


def model_metrics_middleware(emit):
    # Keep the SDK optional for injected runners and lightweight tests.
    from agent_framework import ChatMiddleware, ResponseStream

    class ModelMetrics(ChatMiddleware):
        def __init__(self):
            self.calls = 0

        async def process(self, context, call_next):
            self.calls += 1
            call_number = self.calls
            started = perf_counter()
            first_output = None
            finished = False

            async def finish(outcome, response=None):
                nonlocal finished
                if finished:
                    return
                finished = True
                usage = getattr(response, "usage_details", None) or {}
                await emit(
                    {
                        "category": "model.call",
                        "call": call_number,
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        "time_to_first_output_ms": first_output,
                        "input_tokens": usage.get("input_token_count"),
                        "output_tokens": usage.get("output_token_count"),
                        "outcome": outcome,
                    }
                )

            def update(chunk):
                nonlocal first_output
                if first_output is None and any(
                    item.type in {"text", "text_reasoning", "function_call"}
                    for item in chunk.contents
                ):
                    first_output = round((perf_counter() - started) * 1000, 3)
                return chunk

            async def result(response):
                await finish("completed", response)
                return response

            try:
                await call_next()
                if context.stream:
                    stream = context.result

                    async def measured():
                        try:
                            async for chunk in stream:
                                yield update(chunk)
                            await result(await stream.get_final_response())
                        except BaseException as exc:
                            # Exception type only: provider errors can embed secrets.
                            await finish(type(exc).__name__)
                            raise
                        finally:
                            await stream.close()

                    context.result = ResponseStream(
                        measured(), finalizer=lambda _: stream.get_final_response()
                    )
                else:
                    await result(context.result)
            except BaseException as exc:
                await finish(type(exc).__name__)
                raise

    return ModelMetrics()
