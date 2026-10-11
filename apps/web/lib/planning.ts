/** Per-product planning overrides: form state <-> PATCH /products/{id}/planning body. */

export type PlanningOverrides = {
  preferred_supplier_id: string | null;
  lead_time_days: number | null;
  target_cover_days: number | null;
  service_level: string | null;
};

export type OverrideForm = {
  preferred_supplier_id: string;
  lead_time_days: string;
  target_cover_days: string;
  service_level: string;
};

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export function toForm(p: Partial<PlanningOverrides>): OverrideForm {
  return {
    preferred_supplier_id: str(p.preferred_supplier_id),
    lead_time_days: str(p.lead_time_days),
    target_cover_days: str(p.target_cover_days),
    service_level: p.service_level == null ? "" : String(Number(p.service_level)),
  };
}

/** Only the fields that changed; a blank field sends null (= back to the default).
 * Returns an error message instead when a value is out of range. */
export function overridePatch(
  before: OverrideForm,
  form: OverrideForm,
): { body: Partial<PlanningOverrides> } | { error: string } {
  const body: Partial<PlanningOverrides> = {};
  if (form.preferred_supplier_id !== before.preferred_supplier_id)
    body.preferred_supplier_id = form.preferred_supplier_id || null;
  const int = (k: "lead_time_days" | "target_cover_days", min: number, label: string) => {
    if (form[k] === before[k]) return null;
    if (form[k].trim() === "") {
      body[k] = null;
      return null;
    }
    const n = Number(form[k]);
    if (!Number.isInteger(n) || n < min || n > 365) return `${label} must be a whole number from ${min} to 365`;
    body[k] = n;
    return null;
  };
  const e1 = int("lead_time_days", 0, "Lead time");
  if (e1) return { error: e1 };
  const e2 = int("target_cover_days", 1, "Target cover");
  if (e2) return { error: e2 };
  if (form.service_level !== before.service_level) {
    if (form.service_level.trim() === "") body.service_level = null;
    else {
      const n = Number(form.service_level);
      if (!(n >= 0.5 && n <= 0.999)) return { error: "Service level must be between 0.5 and 0.999" };
      body.service_level = String(n);
    }
  }
  return { body };
}
