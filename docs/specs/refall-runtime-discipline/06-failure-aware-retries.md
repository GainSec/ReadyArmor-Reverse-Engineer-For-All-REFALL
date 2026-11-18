# Runtime retries

Recoverable runtime failures use a bounded retry policy.
The default limit is two attempts with a five-second delay.
Repair prompts carry a bounded portion of the previous output.
Exhausted retries preserve pending work.

Read [Evidence requirements](../../evidence.md) and [API reference](../../api.md) for the operating contract.
