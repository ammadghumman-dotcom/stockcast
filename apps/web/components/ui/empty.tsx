import { Button } from "./button";

export function Empty({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: { label: string; onClick?: () => void; href?: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-10 text-center">
      <p className="font-medium">{title}</p>
      {body ? <p className="max-w-md text-sm text-muted-foreground">{body}</p> : null}
      {action ? (
        action.href ? (
          <Button asChild variant="outline" size="sm">
            <a href={action.href}>{action.label}</a>
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        )
      ) : null}
    </div>
  );
}
