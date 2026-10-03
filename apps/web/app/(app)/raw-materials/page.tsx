"use client";

import { useProducts, useRecommendations } from "@/lib/hooks";
import { PageHeader } from "@/components/shell";
import { ProductsTable } from "@/components/products-table";

export default function RawMaterialsPage() {
  const products = useProducts();
  const recs = useRecommendations();
  const raw = products.data?.filter((p) => p.type === "raw_material");
  return (
    <>
      <PageHeader title="Raw materials" sub="Requirements derived from the finished-goods plan through the bill of materials" />
      <ProductsTable products={raw} recs={recs.data} loading={products.isLoading || recs.isLoading} emptyTitle="No raw materials yet — add BOM lines to see component requirements" />
    </>
  );
}
