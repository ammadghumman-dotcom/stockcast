/** Globals and custom elements provided by App Bridge + Polaris web components (CDN scripts). */
import type * as React from "react";

type ShopifyGlobal = {
  idToken: () => Promise<string>;
  toast: { show: (message: string, opts?: { isError?: boolean; duration?: number }) => void };
  loading: (on: boolean) => void;
  config: { shop?: string; host?: string; apiKey?: string };
};

declare global {
  interface Window {
    shopify?: ShopifyGlobal;
  }
}

type PolarisProps = React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
  [attr: string]: unknown;
};

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "s-page": PolarisProps;
      "s-section": PolarisProps;
      "s-stack": PolarisProps;
      "s-box": PolarisProps;
      "s-heading": PolarisProps;
      "s-paragraph": PolarisProps;
      "s-text": PolarisProps;
      "s-button": PolarisProps;
      "s-link": PolarisProps;
      "s-badge": PolarisProps;
      "s-banner": PolarisProps;
      "s-spinner": PolarisProps;
      "s-table": PolarisProps;
      "s-table-header-row": PolarisProps;
      "s-table-header": PolarisProps;
      "s-table-body": PolarisProps;
      "s-table-row": PolarisProps;
      "s-table-cell": PolarisProps;
      "s-grid": PolarisProps;
      "s-ordered-list": PolarisProps;
      "s-list-item": PolarisProps;
      "s-app-nav": PolarisProps;
    }
  }
}

export {};
