import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stockcast",
  description: "AI demand forecasting and raw-material planning for ecommerce brands",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
