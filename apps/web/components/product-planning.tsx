"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import type { Product } from "@stockcast/shared";

import { unwrap } from "@/lib/api";
import { useAction, useCanEdit, useOrgQuery, useSuppliers } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { overridePatch, toForm, type OverrideForm } from "@/lib/planning";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/input";

/** Preferred supplier and per-product planning overrides (blank = the org default). */
export function ProductPlanning({ product }: { product: Product }) {
  const api = useApi();
  const editable = useCanEdit();
  const suppliers = useSuppliers();
  const defaults = useOrgQuery(["planning-settings"], async () => unwrap(await api.GET("/planning-settings")));
  const before = toForm(product);
  const [form, setForm] = useState<OverrideForm>(before);
  const [saved, setSaved] = useState(false);
  useEffect(() => setForm(toForm(product)), [product]);

  const save = useAction(
    async (body: object) =>
      unwrap(await api.PATCH("/products/{product_id}/planning", { params: { path: { product_id: product.id } }, body: body as never })),
    { success: "Planning settings saved", invalidate: ["product", "products"], onSuccess: () => setSaved(true) },
  );
  const replan = useAction(async () => unwrap(await api.POST("/planning-runs")), {
    success: "Planning started; recommendations update in a minute",
    invalidate: ["planning-runs", "recommendations"],
    onSuccess: () => setSaved(false),
  });

  const d = defaults.data;
  const set = (k: keyof OverrideForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const dirty = JSON.stringify(form) !== JSON.stringify(before);
  const submit = () => {
    const r = overridePatch(before, form);
    if ("error" in r) toast.error(r.error);
    else save.mutate(r.body);
  };

  return (
    <Card>
      <CardHeader><CardTitle>Planning for this product</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Preferred supplier" hint="Reorders go to this supplier. Default: the cheapest supplier that stocks it.">
            <NativeSelect value={form.preferred_supplier_id} onChange={set("preferred_supplier_id")} disabled={!editable} data-testid="preferred-supplier">
              <option value="">Default (cheapest supplier)</option>
              {suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.lead_time_days}d lead</option>)}
            </NativeSelect>
          </Field>
          <Field label="Lead time (days)" hint="Leave blank to use the supplier's lead time.">
            <Input type="number" min={0} value={form.lead_time_days} onChange={set("lead_time_days")} disabled={!editable} placeholder="supplier default" data-testid="override-lead_time_days" />
          </Field>
          <Field label="Target cover (days)">
            <Input type="number" min={1} value={form.target_cover_days} onChange={set("target_cover_days")} disabled={!editable} placeholder={d ? `org default ${d.target_cover_days}` : ""} data-testid="override-target_cover_days" />
          </Field>
          <Field label="Service level (0.5–0.999)">
            <Input type="number" step={0.01} value={form.service_level} onChange={set("service_level")} disabled={!editable} placeholder={d ? `org default ${Number(d.service_level)}` : ""} data-testid="override-service_level" />
          </Field>
        </div>
        {editable ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={!dirty} loading={save.isPending} onClick={submit} data-testid="save-product-planning">Save</Button>
            {saved ? (
              <>
                <span className="text-xs text-muted-foreground">Applies from the next plan.</span>
                <Button size="sm" variant="outline" loading={replan.isPending} onClick={() => replan.mutate()} data-testid="replan">Re-plan now</Button>
              </>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
