"use client";

import { useEffect, useState } from "react";
import { Check, ChevronDown, Copy, ExternalLink, KeyRound, RefreshCw } from "lucide-react";
import { getConnections, removeProviderKey, saveProviderKey, type Connections, type ProviderConnection, type SubscriptionStatus } from "@/lib/api";
import { keyProviders, type ModelProvider } from "@/lib/model-catalog";
import { ProviderLogo } from "@/components/provider-logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const subscriptions = [
  { id: "codex", name: "Codex", plan: "ChatGPT subscription", logo: "openai", command: "codex login", logout: "codex logout", docs: "https://developers.openai.com/codex/auth/", detail: "Uses the ChatGPT account signed in to Codex on the host. Builds use this connection when the server provider is Codex." },
  { id: "claude", name: "Claude Code", plan: "Claude subscription", logo: "anthropic", command: "claude auth login", logout: "claude auth logout", docs: "https://code.claude.com/docs/en/authentication", detail: "Sign in with your Claude subscription on the host. Account setup is available here; the Claude build adapter is not available yet." },
] as const;
const statusLabels: Record<SubscriptionStatus, string> = {
  connected: "Signed in", signed_out: "Not signed in", api_key: "Using an API key",
  unavailable: "CLI not installed", unknown: "Not checked",
};
const messageOf = (reason: unknown) => reason instanceof Error ? reason.message : "Connection settings could not be updated.";

function CopyCommand({ command }: { command: string }) {
  const [message, setMessage] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(command); setMessage("Copied"); }
    catch { setMessage("Select and copy the command above."); }
  }
  return <div className="space-y-1">
    <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-1.5">
      <code className="select-all text-xs">{command}</code>
      <Button type="button" size="icon-sm" variant="ghost" aria-label={`Copy ${command}`} onClick={copy}>{message === "Copied" ? <Check /> : <Copy />}</Button>
    </div>
    <p role="status" className="text-xs text-muted-foreground">{message}</p>
  </div>;
}

function SubscriptionCard({ account, status }: { account: typeof subscriptions[number]; status: SubscriptionStatus }) {
  return <div className="space-y-4 rounded-lg border p-4" data-testid={`subscription-${account.id}`}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div className="flex items-center gap-2.5">
        <ProviderLogo provider={account.logo} className="size-5" />
        <div><p className="text-sm font-medium">{account.name}</p><p className="text-xs text-muted-foreground">{account.plan}</p></div>
      </div>
      <Badge variant={status === "connected" ? "secondary" : "outline"}>{statusLabels[status]}</Badge>
    </div>
    <p className="text-xs leading-relaxed text-muted-foreground">{account.detail}</p>
    <Collapsible>
      <CollapsibleTrigger asChild><Button type="button" variant="outline" size="sm" className="w-full">{status === "connected" ? "Manage account" : "Set up account"}<ChevronDown /></Button></CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 pt-3">
        <p className="text-xs text-muted-foreground">Run on the machine hosting the worker, then finish sign-in in your browser. The host checks every 30 seconds; refresh connections after signing in.</p>
        <CopyCommand command={account.command} />
        <p className="text-xs text-muted-foreground">To switch accounts, sign out first:</p>
        <CopyCommand command={account.logout} />
        <a href={account.docs} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs underline underline-offset-4">Sign-in guide<ExternalLink className="size-3" /></a>
      </CollapsibleContent>
    </Collapsible>
  </div>;
}

function ProviderKeyForm({ provider, connection, disabled, onChange }: {
  provider: ModelProvider; connection?: ProviderConnection; disabled: boolean; onChange: (connection: ProviderConnection) => void;
}) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function update(remove = false) {
    setPending(true); setError(""); setMessage("");
    try {
      const next = remove ? await removeProviderKey(provider.id) : await saveProviderKey(provider.id, key.trim());
      onChange(next); setKey("");
      setMessage(remove ? (next.source === "environment" ? "Saved key removed. The environment key is still configured." : "Key removed.") : "Key saved. Provider access has not been verified.");
    } catch (reason) { setError(messageOf(reason)); }
    finally { setPending(false); }
  }
  return <Collapsible open={open} onOpenChange={(value) => { setOpen(value); if (!value) { setKey(""); setError(""); setMessage(""); } }} className="border-b last:border-b-0" data-testid={`provider-${provider.id}`}>
    <CollapsibleTrigger className="flex w-full items-center gap-3 py-4 text-left hover:text-foreground/80">
      <ProviderLogo provider={provider.logo} className="size-5 shrink-0" />
      <div className="min-w-0 flex-1"><p className="text-sm font-medium">{provider.name}</p><p className="truncate text-xs text-muted-foreground">{provider.models.join(" · ")}</p></div>
      <Badge variant="outline" className="shrink-0">{connection?.source === "saved" ? "Key saved" : connection?.source === "environment" ? "Environment" : "No key"}</Badge>
      <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
    </CollapsibleTrigger>
    <CollapsibleContent className="space-y-4 pb-5 pl-8">
      <div className="flex flex-wrap gap-1.5">{provider.models.map((model) => <Badge key={model} variant="secondary" className="font-mono text-[10px]">{model}</Badge>)}</div>
      {provider.unavailable?.map((model) => <p key={model.name} className="text-xs text-muted-foreground"><code>{model.name}</code> — {model.reason}; unavailable through BYOK.</p>)}
      <form onSubmit={(event) => { event.preventDefault(); void update(); }} className="space-y-2">
        <Label htmlFor={`key-${provider.id}`}>{provider.name} API key</Label>
        <Input id={`key-${provider.id}`} type="password" autoComplete="off" spellCheck={false} value={key} onChange={(event) => { setKey(event.target.value); setError(""); setMessage(""); }} placeholder={connection?.configured ? "Enter a replacement key" : "Paste your API key"} disabled={pending || disabled} maxLength={4096} aria-describedby={`key-detail-${provider.id}`} />
        <p id={`key-detail-${provider.id}`} className="text-xs text-muted-foreground">{provider.id === "meta" ? "Used by new builds when the server provider is Meta. A saved key takes priority over META_API_KEY." : "Save a key for these models. Build support for this provider is not available yet."}</p>
        <div className="flex flex-wrap gap-2 pt-1">
          <Button type="submit" size="sm" disabled={pending || disabled || key.trim().length < 8}>{pending ? "Updating…" : connection?.configured ? "Replace key" : "Save key"}</Button>
          {connection?.source === "saved" ? <Button type="button" variant="outline" size="sm" disabled={pending || disabled} onClick={() => void update(true)}>Remove key</Button> : null}
        </div>
      </form>
      {connection?.source === "environment" ? <p className="text-xs text-muted-foreground">The current key comes from the server environment. Remove it there to disconnect fully.</p> : null}
      <p role={error ? "alert" : "status"} className={`text-xs ${error ? "text-destructive" : "text-muted-foreground"}`}>{error || message}</p>
    </CollapsibleContent>
  </Collapsible>;
}

export function ProviderConnections() {
  const [connections, setConnections] = useState<Connections>();
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    getConnections(controller.signal).then(setConnections, (reason: unknown) => { if (!controller.signal.aborted) setError(messageOf(reason)); });
    return () => controller.abort();
  }, []);
  async function refresh() {
    setRefreshing(true); setError("");
    try { setConnections(await getConnections()); }
    catch (reason) { setError(messageOf(reason)); }
    finally { setRefreshing(false); }
  }
  function changed(connection: ProviderConnection) {
    setConnections((current) => current ? { ...current, keys: current.keys.map((key) => key.provider === connection.provider ? connection : key) } : current);
  }
  const query = search.trim().toLowerCase();
  const visible = keyProviders.filter((provider) => `${provider.name} ${provider.models.join(" ")}`.toLowerCase().includes(query));
  const configured = connections?.keys.filter((key) => key.configured).length ?? 0;
  return <section className="space-y-6" aria-label="Model connections">
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1.5"><CardTitle>Subscription accounts</CardTitle><CardDescription>Use your Claude or ChatGPT subscription through its host CLI.</CardDescription></div>
          <Button type="button" variant="ghost" size="icon-sm" onClick={refresh} disabled={refreshing} aria-label="Refresh connections"><RefreshCw className={refreshing ? "animate-spin" : ""} /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">{subscriptions.map((account) => <SubscriptionCard key={account.id} account={account} status={connections?.subscriptions[account.id] ?? "unknown"} />)}</div>
        <p className="text-xs text-muted-foreground">Sign-in stays on the host. Account passwords and subscription tokens are never stored here. Status reflects CLI sign-in, not remaining quota.</p>
        {!connections && !error ? <p role="status" className="text-xs text-muted-foreground">Loading connections…</p> : null}
        {connections?.subscriptions.checked_at === 0 ? <p className="text-xs text-muted-foreground">Waiting for the host worker to report sign-in status. Start or restart it with <code>make dev</code>.</p> : null}
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3"><CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />Bring your own keys</CardTitle><Badge variant="secondary">{configured} configured</Badge></div>
        <CardDescription>One provider key covers its listed API models. API usage is billed by the provider.</CardDescription>
      </CardHeader>
      <CardContent>
        <Label htmlFor="provider-search" className="sr-only">Search providers or models</Label>
        <Input id="provider-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search providers or models…" className="mb-1" />
        {visible.map((provider) => <ProviderKeyForm key={provider.id} provider={provider} connection={connections?.keys.find((key) => key.provider === provider.id)} disabled={!connections || Boolean(error)} onChange={changed} />)}
        {!visible.length ? <p role="status" className="py-6 text-center text-sm text-muted-foreground">No providers or models match “{search}”.</p> : null}
        <p className="border-t pt-4 text-xs leading-relaxed text-muted-foreground">Keys are stored in a private file on this server, outside design files. They are never returned to the browser. Saving a key does not verify access or change the server&apos;s build provider. Builds currently support Codex and Meta.</p>
      </CardContent>
    </Card>
  </section>;
}
