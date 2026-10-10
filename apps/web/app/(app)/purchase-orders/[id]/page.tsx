"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { API_URL, unwrap } from "@/lib/api";
import { useAction, useCanEdit, useOrgQuery } from "@/lib/hooks";
import { useApi, useOrg } from "@/lib/org";
import { fmtDate, fmtMoney, fmtNum } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Empty } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export default function PurchaseOrderDetail() {
  const { id } = useParams<{ id: string }>();
  const api = useApi();
  const { authHeaders } = useOrg();
  const editable = useCanEdit();
  const po = useOrgQuery(["purchase-orders", id], async () => unwrap(await api.GET("/purchase-orders/{po_id}", { params: { path: { po_id: id } } })));
  const [receiving, setReceiving] = useState(false);
  const [qty, setQty] = useState<Record<string, string>>({});

  const usePoAction = (path: "send" | "mark-sent" | "receive", body?: { lines: Record<string, string> }) =>
    useAction(
      async () => unwrap(await api.POST(`/purchase-orders/{po_id}/${path}` as "/purchase-orders/{po_id}/send", { params: { path: { po_id: id } }, body: body as never })),
      { invalidate: ["purchase-orders", "recommendations", "products"], success: path === "receive" ? "Stock received" : "Purchase order sent", onSuccess: () => setReceiving(false) },
    );
  const send = usePoAction("send");
  const markSent = usePoAction("mark-sent");
  const receive = usePoAction("receive", { lines: qty });
  const receiveAll = usePoAction("receive");

  if (po.isLoading) return <Skeleton className="h-48" />;
  if (!po.data) return <Empty title="Purchase order not found" action={{ label: "All purchase orders", href: "/purchase-orders" }} />;
  const p = po.data;
  const download = (ext: "csv" | "pdf") => {
    const u = `${API_URL}/purchase-orders/${id}/export.${ext}`;
    authHeaders().then((h) => fetch(u, { headers: h })).then(async (r) => {
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${p.number}.${ext}`;
      a.click();
    });
  };

  return (
    <>
      <PageHeader
        title={p.number}
        sub={`${p.supplier_name ?? ""} · expected ${fmtDate(p.expected_date)}`}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => download("csv")}>CSV</Button>
            <Button variant="outline" size="sm" onClick={() => download("pdf")}>PDF</Button>
            {editable && p.status === "draft" ? (
              <>
                <Button size="sm" variant="secondary" loading={markSent.isPending} onClick={() => markSent.mutate()} data-testid="mark-sent">Mark sent</Button>
                <Button size="sm" loading={send.isPending} onClick={() => send.mutate()} data-testid="send">Email supplier</Button>
              </>
            ) : null}
            {editable && p.status === "sent" ? (
              <>
                <Button size="sm" variant="secondary" onClick={() => setReceiving(true)}>Receive partially</Button>
                <Button size="sm" loading={receiveAll.isPending} onClick={() => receiveAll.mutate()} data-testid="receive-all">Receive all</Button>
              </>
            ) : null}
          </>
        }
      />
      <p className="mb-3"><StatusBadge status={p.status} /> {p.sent_at ? <span className="ml-2 text-xs text-muted-foreground">sent {fmtDate(p.sent_at)}</span> : null}{p.received_at ? <span className="ml-2 text-xs text-muted-foreground">received {fmtDate(p.received_at)}</span> : null}</p>
      <Table>
        <THead><TR><TH>#</TH><TH>SKU</TH><TH className="text-right">Qty</TH><TH className="text-right">Received</TH><TH className="text-right">Unit price</TH><TH className="text-right">Total</TH></TR></THead>
        <TBody>
          {p.lines.map((l) => (
            <TR key={l.id} data-testid="po-line">
              <TD>{l.line_no}</TD><TD className="font-medium">{l.sku}</TD>
              <TD className="text-right tabular-nums">{fmtNum(l.qty)}</TD>
              <TD className="text-right tabular-nums">{fmtNum(l.received_qty)}</TD>
              <TD className="text-right tabular-nums">{fmtNum(l.unit_price, 4)}</TD>
              <TD className="text-right tabular-nums">{fmtMoney(Number(l.qty) * Number(l.unit_price), p.currency)}</TD>
            </TR>
          ))}
          <TR><TD colSpan={5} className="text-right font-medium">Total</TD><TD className="text-right font-medium tabular-nums">{fmtMoney(p.total, p.currency)}</TD></TR>
        </TBody>
      </Table>
      {p.notes ? <p className="mt-3 text-xs text-muted-foreground">{p.notes}</p> : null}

      <Dialog open={receiving} onOpenChange={setReceiving}>
        <DialogContent title="Receive quantities" description="Leave blank for lines not received yet.">
          {p.lines.map((l) => (
            <div key={l.id} className="flex items-center gap-3">
              <span className="w-32 text-sm">{l.sku}</span>
              <Input type="number" min={0} max={Number(l.qty) - Number(l.received_qty)} placeholder={`${Number(l.qty) - Number(l.received_qty)} open`} value={qty[l.id] ?? ""} onChange={(e) => setQty((q) => ({ ...q, [l.id]: e.target.value }))} />
            </div>
          ))}
          <Button loading={receive.isPending} onClick={() => receive.mutate()}>Receive</Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
