"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { unwrap } from "@/lib/api";
import { defaultSelection, inviteSummary, stars } from "@/lib/beta";
import { useAction, useIsStaff, useOrgQuery } from "@/lib/hooks";
import { useApi } from "@/lib/org";
import { fmtDate } from "@/lib/utils";
import { PageHeader } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, Tile } from "@/components/ui/card";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Empty } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

export default function StaffBetaPage() {
  const staff = useIsStaff();
  const api = useApi();
  const [showAll, setShowAll] = useState(false);
  const waitlist = useOrgQuery(["staff-waitlist", showAll], async () =>
    unwrap(await api.GET("/staff/beta/waitlist", { params: { query: { all: showAll } } })), staff);
  const workspaces = useOrgQuery(["staff-beta-workspaces"], async () => unwrap(await api.GET("/staff/beta/workspaces")), staff);
  const feedback = useOrgQuery(["staff-feedback"], async () =>
    unwrap(await api.GET("/staff/beta/feedback", { params: { query: { days: 30 } } })), staff);

  const rows = useMemo(() => waitlist.data ?? [], [waitlist.data]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(defaultSelection(rows)), [rows]);
  const [confirm, setConfirm] = useState(false);
  const [grantKey, setGrantKey] = useState("");

  const invite = useAction(
    async (emails: string[]) => unwrap(await api.POST("/staff/beta/invites", { body: { emails, resend: false } })),
    {
      invalidate: ["staff-waitlist"],
      onSuccess: (r) => {
        const s = inviteSummary(r);
        (s.ok ? toast.success : toast.error)(s.text);
        setConfirm(false);
      },
    },
  );
  const grant = useAction(
    async (v: { key: string; on: boolean }) => unwrap(await api.POST("/staff/beta/grant", { body: v })),
    {
      invalidate: ["staff-beta-workspaces"],
      onSuccess: (w) => { toast.success(`${w.name}: beta ${w.is_beta ? "on" : "off"}`); setGrantKey(""); },
    },
  );

  if (!staff) return <Empty title="Not found" body="This page doesn't exist." />;

  const toggle = (email: string) =>
    setSelected((s) => { const n = new Set(s); if (n.has(email)) n.delete(email); else n.add(email); return n; });
  const fits = rows.filter((r) => r.beta_fit);
  const chosen = [...selected];

  return (
    <>
      <PageHeader title="Beta program" sub="Staff only · invite waitlist brands, turn on beta pricing, read feedback" />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="Waitlist fits" value={waitlist.isLoading ? "–" : String(fits.length)} sub="make products · 2+ channels" />
        <Tile label="Invited" value={waitlist.isLoading ? "–" : String(rows.filter((r) => r.invited_at).length)} />
        <Tile label="Beta workspaces" value={workspaces.isLoading ? "–" : String(workspaces.data?.length ?? 0)} />
        <Tile label="Feedback (30 days)" value={feedback.isLoading ? "–" : String(feedback.data?.length ?? 0)} />
      </div>

      <Card className="mb-4">
        <CardHeader><CardTitle>Waitlist</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} data-testid="show-all" />
              Show everyone (not just beta fits)
            </label>
            <Button disabled={!chosen.length} onClick={() => setConfirm(true)} data-testid="send-invites">
              Send invites ({chosen.length})
            </Button>
          </div>
          {waitlist.isLoading ? <Skeleton className="h-32" /> : !rows.length ? (
            <Empty title="No one yet" body={showAll ? "Nobody has joined the waitlist from the site yet." : "No signups fit the beta yet. Tick “Show everyone” to see all signups."} />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <THead><TR><TH /><TH>Email</TH><TH>Brand</TH><TH>Channels</TH><TH>Makes</TH><TH>Joined</TH><TH>Invited</TH></TR></THead>
                <TBody>
                  {rows.map((r) => (
                    <TR key={r.id} data-testid="waitlist-row">
                      <TD><input type="checkbox" aria-label={`Select ${r.email}`} checked={selected.has(r.email)} onChange={() => toggle(r.email)} /></TD>
                      <TD className="font-medium">{r.email}{r.notes ? <div className="max-w-xs truncate text-xs text-muted-foreground" title={r.notes}>{r.notes}</div> : null}</TD>
                      <TD>{r.company ?? "–"}{r.name ? <div className="text-xs text-muted-foreground">{r.name}</div> : null}</TD>
                      <TD><div className="flex flex-wrap gap-1">{r.channels.map((c) => <Badge key={c} variant="outline">{c}</Badge>)}</div></TD>
                      <TD>{r.makes_products ? "Yes" : "No"}{r.beta_fit ? <Badge className="ml-2">fit</Badge> : null}</TD>
                      <TD className="whitespace-nowrap text-xs">{fmtDate(r.created_at)}</TD>
                      <TD className="whitespace-nowrap text-xs">{r.invited_at ? fmtDate(r.invited_at) : "–"}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Beta workspaces</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">Invited brands get beta pricing (50% off for 6 months) automatically when they create their workspace. Use this for anyone else.</p>
            <div className="flex gap-2">
              <Input placeholder="workspace slug, id, shop domain or owner email" value={grantKey} onChange={(e) => setGrantKey(e.target.value)} data-testid="grant-key" />
              <Button disabled={grantKey.trim().length < 2} loading={grant.isPending} onClick={() => grant.mutate({ key: grantKey.trim(), on: true })} data-testid="grant-beta">Grant beta</Button>
            </div>
            {!workspaces.data?.length ? <p className="text-sm text-muted-foreground">No beta workspaces yet.</p> : (
              <ul className="divide-y text-sm">
                {workspaces.data.map((w) => (
                  <li key={w.id} className="flex items-center justify-between py-2">
                    <span><span className="font-medium">{w.name}</span> <span className="text-xs text-muted-foreground">{w.slug} · {w.plan}</span></span>
                    <Button size="sm" variant="ghost" onClick={() => grant.mutate({ key: w.slug, on: false })}>Remove</Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Feedback · last 30 days</CardTitle></CardHeader>
          <CardContent>
            {!feedback.data?.length ? <p className="text-sm text-muted-foreground">No feedback yet.</p> : (
              <ul className="space-y-3 text-sm">
                {feedback.data.map((f) => (
                  <li key={f.id} className="rounded-md border p-3">
                    <div className="mb-1 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
                      <span>{f.workspace ?? "–"} · {f.actor}{f.page ? ` · ${f.page}` : ""}</span>
                      <span><span className="text-amber-600">{stars(f.rating)}</span> {fmtDate(f.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-wrap">{f.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent title={`Send ${chosen.length} beta invite${chosen.length === 1 ? "" : "s"}?`} description="Each person gets one email from Stockcast with a sign-up link and the beta discount. People already invited are skipped.">
          <ul className="max-h-48 overflow-y-auto text-sm">{chosen.map((e) => <li key={e}>{e}</li>)}</ul>
          <div className="flex gap-2">
            <Button loading={invite.isPending} onClick={() => invite.mutate(chosen)} data-testid="confirm-invites">Send invites</Button>
            <Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
