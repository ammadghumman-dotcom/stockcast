/** Supplier item form -> API body (price, pack size, optional lead-time override). */

export type ItemForm = { product_id: string; price: string; pack_size: string; lead_time_days: string };

export const emptyItem: ItemForm = { product_id: "", price: "", pack_size: "1", lead_time_days: "" };

export type ItemBody = { product_id: string; price: string; pack_size: number; lead_time_days: number | null };

export function itemBody(f: ItemForm): { body: ItemBody } | { error: string } {
  if (!f.product_id) return { error: "Pick a product" };
  const price = Number(f.price);
  if (f.price.trim() === "" || !Number.isFinite(price) || price < 0) return { error: "Price must be 0 or more" };
  const pack = Number(f.pack_size || "1");
  if (!Number.isInteger(pack) || pack < 1) return { error: "Pack size must be a whole number of 1 or more" };
  let lead: number | null = null;
  if (f.lead_time_days.trim() !== "") {
    lead = Number(f.lead_time_days);
    if (!Number.isInteger(lead) || lead < 0 || lead > 365) return { error: "Lead time must be 0–365 days, or blank to use the supplier's" };
  }
  return { body: { product_id: f.product_id, price: String(price), pack_size: pack, lead_time_days: lead } };
}

export function toItemForm(i: { product_id: string; price: string | number; pack_size: number; lead_time_days: number | null }): ItemForm {
  return {
    product_id: i.product_id,
    price: String(Number(i.price)),
    pack_size: String(i.pack_size),
    lead_time_days: i.lead_time_days == null ? "" : String(i.lead_time_days),
  };
}
