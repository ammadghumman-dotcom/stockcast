"use client";

import { useMemo, useState } from "react";

import type { Supplier, SupplierItem } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useCanEdit, useOrgQuery, useProducts } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { emptyItem, fmtPrice, itemBody, toItemForm, type ItemForm } from "@/lib/supplier-items";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Empty } from "@/components/ui/empty";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

/** Settings → Suppliers → Items: what this supplier charges per product (CAT-04). */
export function SupplierItemsDialog({ supplier, onClose }: { supplier: Supplier | null; onClose: () => void }) {
  return (
    <Dialog open={!!supplier} onOpenChange={(o) => { if (!o) onClose(); }}>
      {supplier ? (
        <DialogContent title={`Items — ${supplier.name}`} description={`Price per unit in ${supplier.currency}. Planning rounds orders up to the pack size and uses the item lead time ahead of the supplier's ${supplier.lead_time_days} days.`} className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <SupplierItems supplier={supplier} />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function SupplierItems({ supplier }: { supplier: Supplier }) {
  const api = useApi();
  const editable = useCanEdit();
  const products = useProducts();
  const key = ["supplier-items", supplier.id];
  const items = useOrgQuery(key, async () =>
    unwrap(await api.GET("/suppliers/{supplier_id}/items", { params: { path: { supplier_id: supplier.id } } })),
  );
  const [editing, setEditing] = useState<string | null>(null); // item id, "new" or null
  const [form, setForm] = useState<ItemForm>(emptyItem);
  const [error, setError] = useState<string | null>(null);

  const taken = useMemo(() => new Set((items.data ?? []).map((i) => i.product_id)), [items.data]);
  const choices = (products.data ?? []).filter((p) => !taken.has(p.id) || p.id === form.product_id);

  const save = useAction(
    async () => {
      const r = itemBody(form);
      if ("error" in r) throw new Error(r.error);
      const path = { supplier_id: supplier.id };
      if (editing && editing !== "new") {
        const { product_id: _ignored, ...patch } = r.body;
        void _ignored;
        return unwrap(await api.PATCH("/suppliers/{supplier_id}/items/{item_id}", { params: { path: { ...path, item_id: editing } }, body: patch }));
      }
      return unwrap(await api.POST("/suppliers/{supplier_id}/items", { params: { path }, body: r.body }));
    },
    { success: "Item saved", invalidate: ["supplier-items"], onSuccess: () => { setEditing(null); setError(null); } },
  );
  const remove = useAction(
    async (item: SupplierItem) => {
      const r = await api.DELETE("/suppliers/{supplier_id}/items/{item_id}", { params: { path: { supplier_id: supplier.id, item_id: item.id } } });
      if (!r.response.ok) unwrap(r as never);
      return null;
    },
    { success: "Item removed", invalidate: ["supplier-items"] },
  );

  const start = (id: string, f: ItemForm) => { setEditing(id); setForm(f); setError(null); };
  const set = (k: keyof ItemForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setError(null);
    setForm((x) => ({ ...x, [k]: e.target.value }));
  };
  const submit = () => { const r = itemBody(form); if ("error" in r) setError(r.error); else save.mutate(undefined); };

  const editor = (isNew: boolean) => (
    <div className="space-y-2 rounded-md border bg-muted/30 p-3" data-testid="supplier-item-form">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
        <Field label="Product">
          <NativeSelect value={form.product_id} onChange={set("product_id")} disabled={!isNew} data-testid="item-product">
            <option value="">Choose…</option>
            {choices.map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
          </NativeSelect>
        </Field>
        <Field label={`Price (${supplier.currency})`}><Input type="number" min={0} step="any" value={form.price} onChange={set("price")} data-testid="item-price" /></Field>
        <Field label="Pack size"><Input type="number" min={1} step={1} value={form.pack_size} onChange={set("pack_size")} data-testid="item-pack" /></Field>
        <Field label="Lead time (days)"><Input type="number" min={0} step={1} placeholder={`${supplier.lead_time_days} (supplier)`} value={form.lead_time_days} onChange={set("lead_time_days")} data-testid="item-lead" /></Field>
      </div>
      {error ? <p className="text-xs text-red-600" data-testid="item-error">{error}</p> : null}
      <div className="flex gap-2">
        <Button size="sm" loading={save.isPending} onClick={submit} data-testid="save-item">Save</Button>
        <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
      </div>
    </div>
  );

  if (items.isLoading) return <Skeleton className="h-32" />;
  const rows = items.data ?? [];
  return (
    <div className="space-y-3">
      {!rows.length ? (
        editing === "new" ? null : 
        <Empty title="No items yet" body="Add the products this supplier sells you, with their price, pack size and lead time." />
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <THead><TR><TH>Product</TH><TH className="text-right">Price</TH><TH className="text-right">Pack</TH><TH className="text-right">Lead (d)</TH><TH /></TR></THead>
            <TBody>
              {rows.map((i) => (
                <TR key={i.id} data-testid="supplier-item-row">
                  <TD><span className="font-medium">{i.sku}</span> <span className="text-xs text-muted-foreground">{i.product_name}</span></TD>
                  <TD className="text-right tabular-nums">{fmtPrice(i.price)} <span className="text-xs text-muted-foreground">/{i.unit}</span></TD>
                  <TD className="text-right tabular-nums">{i.pack_size}</TD>
                  <TD className="text-right tabular-nums">{i.effective_lead_time_days}{i.lead_time_days == null ? <span className="text-xs text-muted-foreground"> (supplier)</span> : null}</TD>
                  <TD className="whitespace-nowrap text-right">
                    {editable ? (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => start(i.id, toItemForm(i))} data-testid="edit-item">Edit</Button>
                        <Button size="sm" variant="ghost" loading={remove.isPending && remove.variables?.id === i.id} onClick={() => remove.mutate(i)} data-testid="remove-item">Remove</Button>
                      </>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}
      {editing ? editor(editing === "new") : editable ? (
        <Button size="sm" onClick={() => start("new", emptyItem)} data-testid="add-item">Add item</Button>
      ) : null}
    </div>
  );
}
