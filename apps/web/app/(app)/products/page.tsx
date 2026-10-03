"use client";

import { useProducts, useRecommendations } from "@/lib/hooks";
import { PageHeader } from "@/components/shell";
import { ProductsTable } from "@/components/products-table";

export default function ProductsPage() {
  const products = useProducts();
  const recs = useRecommendations();
  const finished = products.data?.filter((p) => p.type !== "raw_material");
  return (
    <>
      <PageHeader title="Products" sub="Finished goods and bundles" />
      <ProductsTable products={finished} recs={recs.data} loading={products.isLoading || recs.isLoading} emptyTitle="No products yet" />
    </>
  );
}
