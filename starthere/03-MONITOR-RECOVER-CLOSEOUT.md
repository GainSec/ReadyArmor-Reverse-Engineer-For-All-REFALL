# Monitor and close a subject

1. Examine `/api/refall/ops/debug/{subject}/live`.
2. Examine coverage and pending actions.
3. Request `loop update` when a bounded recovery cycle is necessary.
4. Resolve missing evidence and capability requests.
5. Run `report draft`.
6. Run `report enrich`.
7. Read `/api/workbenches/{slug}/closeout/gate`.
8. Resolve each closeout condition.
9. Request loop closeout.
