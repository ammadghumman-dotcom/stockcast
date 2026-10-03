"use client";

import Link from "next/link";

import { unwrap } from "@/lib/api";
import { useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate, fmtMoney } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { StatusBadge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/empty";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export default function PurchaseOrdersPage() {
  const api = useApi();
  const pos = useOrgQuery(["purchase-orders"], async () => unwrap(await api.GET("/purchase-orders", { params: { query: { limit: 200 } } })));
  return (
    <>
      <PageHeader title="Purchase orders" />
      {pos.isLoading ? <TableSkeleton /> : !pos.data?.length ? (
        <Empty title="No purchase orders" body="Select reorder recommendations and create a PO." action={{ label: "Recommendations", href: "/recommendations" }} />
      ) : (
        <Table>
          <THead><TR><TH>Number</TH><TH>Supplier</TH><TH>Status</TH><TH className="text-right">Lines</TH><TH className="text-right">Total</TH><TH>Expected</TH></TR></THead>
          <TBody>
            {pos.data.map((po) => (
              <TR key={po.id} data-testid="po-row">
                <TD><Link href={`/purchase-orders/${po.id}`} className="font-medium hover:underline">{po.number}</Link></TD>
                <TD>{po.supplier_name}</TD>
                <TD><StatusBadge status={po.status} /></TD>
                <TD className="text-right">{po.lines.length}</TD>
                <TD className="text-right tabular-nums">{fmtMoney(po.total, po.currency)}</TD>
                <TD>{fmtDate(po.expected_date)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </>
  );
}
