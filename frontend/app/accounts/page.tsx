"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import "../styles.css";
import "./accounts.css";
import "./evidence.css";

type Offer = { id: string; name: string };
type Score = { fit: number; intent: number; engagement: number; timing: number; total: number; classification: string; explanation: Record<string, unknown> };
type Account = { id: string; name: string; domain: string | null; segment: string | null; employee_band: string | null; region: string | null; source: string; status?: string; score: Score | null };
type NewSignal = { signal_type: string; title: string; description: string; source_url: string; evidence: string; occurred_at: string; confidence: number; strength: number };
type NewActivity = { activity_type: "contacted" | "replied" | "meeting" | "opportunity" | "won" | "lost"; channel: string; outcome: string; notes: string };
type AccountContact = { id: string; kind: string; name: string | null; title: string | null; email: string | null; phone: string | null; confidence: number; source_provider: string; source_url: string | null };
type AccountSource = { provider_id: string; external_id: string; source_url: string | null; observed_at: string };
type Workflow = { id: string; account_id: string; account_name: string; status: string; attempts: number; error: string | null };
type WorkflowStep = { name: string; status: string; attempts: number; error: string | null; details: Record<string, unknown> };
const blankSignal: NewSignal = { signal_type: "hiring", title: "", description: "", source_url: "", evidence: "", occurred_at: "", confidence: 0.7, strength: 3 };

async function call(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}` } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Não foi possível concluir a solicitação.");
  return body;
}

export default function AccountsPage() {
  const [token, setToken] = useState("");
  const [offers, setOffers] = useState<Offer[]>([]);
  const [offerId, setOfferId] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [totalAccounts, setTotalAccounts] = useState(0);
  const [offset, setOffset] = useState(0);
  const [classification, setClassification] = useState("");
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [osmKey, setOsmKey] = useState("amenity");
  const [discoveryProvider, setDiscoveryProvider] = useState("osm-overpass");
  const [osmValue, setOsmValue] = useState("");
  const [bbox, setBbox] = useState("");
  const [icpSegments, setIcpSegments] = useState<string[]>([]);
  const [segmentLabel, setSegmentLabel] = useState("");
  const [discoveryJob, setDiscoveryJob] = useState("");
  const [signalAccount, setSignalAccount] = useState("");
  const [signal, setSignal] = useState<NewSignal>(blankSignal);
  const [activityAccount, setActivityAccount] = useState("");
  const [activity, setActivity] = useState<NewActivity>({ activity_type: "contacted", channel: "email", outcome: "", notes: "" });
  const [brief, setBrief] = useState<{ account_id: string; account: string; generated_with: string; data: Record<string, unknown> } | null>(null);
  const [signalsFor, setSignalsFor] = useState<string>("");
  const [accountSignals, setAccountSignals] = useState<{ id: string; title: string; description: string; source_url: string | null; occurred_at: string; confidence: number }[]>([]);
  const [contactsFor, setContactsFor] = useState("");
  const [accountContacts, setAccountContacts] = useState<AccountContact[]>([]);
  const [sourcesFor, setSourcesFor] = useState("");
  const [accountSources, setAccountSources] = useState<AccountSource[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowSteps, setWorkflowSteps] = useState<{ id: string; steps: WorkflowStep[] } | null>(null);

  useEffect(() => { const saved = window.localStorage.getItem("le360_token"); if (saved) setToken(saved); }, []);

  useEffect(() => {
    if (!token) return;
    call("/onboarding", token).then(async (company) => {
      const verified: Offer[] = [];
      for (const offer of company?.offers || []) {
        try { const icp = await call(`/offers/${offer.id}/icp`, token); if (icp?.status === "approved") verified.push(offer); } catch { /* ICP ainda não criado */ }
      }
      setOffers(verified);
      if (verified.length) setOfferId(verified[0].id);
    }).catch((error) => setNotice(error.message));
  }, [token]);

  const loadAccounts = useCallback(async () => {
    if (!token || !offerId) return;
    try {
      const params = new URLSearchParams({ limit: "50", offset: String(offset) });
      if (search.trim()) params.set("search", search.trim());
      if (classification) params.set("classification", classification);
      const result = await call(`/offers/${offerId}/accounts?${params}`, token);
      setAccounts(result.items);
      setTotalAccounts(result.total || 0);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar as contas."); }
  }, [token, offerId, offset, search, classification]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);
  useEffect(() => { setOffset(0); }, [offerId]);

  const loadWorkflows = useCallback(async () => {
    if (!token || !offerId) return;
    try {
      const result = await call(`/offers/${offerId}/workflows?limit=50`, token);
      setWorkflows(result.items || []);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar o processamento."); }
  }, [token, offerId]);

  useEffect(() => {
    void loadWorkflows();
    if (!token || !offerId) return;
    const timer = window.setInterval(() => void loadWorkflows(), 5000);
    return () => window.clearInterval(timer);
  }, [token, offerId, loadWorkflows]);

  async function showWorkflow(run: Workflow) {
    if (workflowSteps?.id === run.id) { setWorkflowSteps(null); return; }
    try {
      const result = await call(`/offers/${offerId}/workflows/${run.id}`, token);
      setWorkflowSteps({ id: run.id, steps: result.steps || [] });
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível abrir as etapas."); }
  }

  async function retryWorkflow(run: Workflow) {
    setBusy(true);
    try {
      await call(`/offers/${offerId}/workflows/${run.id}/retry`, token, { method: "POST" });
      setNotice(`Reprocessamento iniciado para ${run.account_name}.`);
      await loadWorkflows();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível reprocessar a conta."); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    if (!token || !offerId) return;
    setDiscoveryJob("");
    call(`/offers/${offerId}/icp`, token).then((icp) => {
      const criteria = icp?.profile?.ideal_customer_profile;
      const segments = Array.isArray(criteria?.segments) ? criteria.segments.filter((value: unknown): value is string => typeof value === "string") : [];
      setIcpSegments(segments); setSegmentLabel(segments[0] || "");
      const saved = icp?.profile?.discovery;
      if (saved?.osm_tag) { setOsmKey(saved.osm_tag.key || "amenity"); setOsmValue(saved.osm_tag.value || ""); }
      if (Array.isArray(saved?.bbox)) setBbox(saved.bbox.join(", "));
      if (saved?.segment_label && segments.includes(saved.segment_label)) setSegmentLabel(saved.segment_label);
    }).catch((error) => setNotice(error instanceof Error ? error.message : "Não foi possível carregar o ICP."));
    call(`/offers/${offerId}/discovery`, token).then((job) => {
      if (job && ["queued", "processing", "retrying"].includes(job.status)) setDiscoveryJob(job.job_id);
    }).catch((error) => setNotice(error instanceof Error ? error.message : "Não foi possível consultar a busca."));
  }, [token, offerId]);

  useEffect(() => {
    if (!discoveryJob || !token) return;
    const poll = async () => {
      try {
        const job = await call(`/jobs/${discoveryJob}`, token);
        if (job.status === "completed") { setDiscoveryJob(""); setNotice("Busca concluída. O processamento das contas continua em segundo plano."); await loadAccounts(); }
        if (job.status === "failed") { setDiscoveryJob(""); setNotice(job.error || "A busca falhou."); }
      } catch (error) { setDiscoveryJob(""); setNotice(error instanceof Error ? error.message : "Não foi possível consultar a busca."); }
    };
    void poll();
    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, [discoveryJob, token, loadAccounts]);

  async function startDiscovery(event: FormEvent) {
    event.preventDefault(); if (!offerId) return;
    const bounds = bbox.split(",").map((part) => Number(part.trim()));
    if (discoveryProvider === "osm-overpass" && (bounds.length !== 4 || bounds.some((value) => !Number.isFinite(value)))) { setNotice("Informe sul, oeste, norte e leste separados por vírgulas."); return; }
    setBusy(true); setNotice("");
    try {
      const icp = await call(`/offers/${offerId}/icp`, token);
      if (icp?.status !== "approved") throw new Error("Aprove o ICP antes de iniciar a busca.");
      if (discoveryProvider === "osm-overpass") await call(`/offers/${offerId}/icp`, token, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "approved", profile: { ...icp.profile, discovery: { osm_tag: { key: osmKey.trim(), value: osmValue.trim() }, bbox: bounds, ...(segmentLabel ? { segment_label: segmentLabel } : {}) } } }) });
      const sources = await call(`/offers/${offerId}/integrations`, token);
      await call(`/offers/${offerId}/integrations`, token, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider_ids: [...new Set([...(sources.provider_ids || []), discoveryProvider])] }) });
      const result = await call(`/offers/${offerId}/discovery?provider_id=${encodeURIComponent(discoveryProvider)}`, token, { method: "POST" });
      setDiscoveryJob(result.job_id); setNotice("Busca iniciada. Aguarde o processamento da fonte.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível iniciar a busca."); }
    finally { setBusy(false); }
  }

  async function saveSignal(event: FormEvent) {
    event.preventDefault(); if (!signalAccount || !offerId) return;
    setBusy(true); setNotice("");
    try {
      await call(`/offers/${offerId}/accounts/${signalAccount}/signals`, token, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...signal, occurred_at: signal.occurred_at ? new Date(signal.occurred_at).toISOString() : null }) });
      setSignalAccount(""); setSignal(blankSignal); await loadAccounts(); setNotice("Sinal registrado; pontuação recalculada.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível registrar o sinal."); }
    finally { setBusy(false); }
  }

  async function generateBrief(account: Pick<Account, "id" | "name">, refresh = false) {
    if (!offerId) return;
    setBusy(true); setNotice("");
    try {
      let result;
      if (!refresh) {
        const response = await fetch(`/api/v1/offers/${offerId}/accounts/${account.id}/brief`, { headers: { Authorization: `Bearer ${token}` } });
        if (response.ok) result = await response.json();
        else if (response.status !== 404) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "Não foi possível abrir o brief."); }
      }
      result ||= await call(`/offers/${offerId}/accounts/${account.id}/brief`, token, { method: "POST" });
      setBrief({ account_id: account.id, account: account.name, generated_with: result.generated_with, data: result.brief });
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível gerar o brief."); }
    finally { setBusy(false); }
  }

  async function showSignals(account: Account) {
    if (!offerId) return;
    if (signalsFor === account.id) { setSignalsFor(""); return; }
    try { setAccountSignals(await call(`/offers/${offerId}/accounts/${account.id}/signals`, token)); setSignalsFor(account.id); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar as evidências."); }
  }

  async function showContacts(account: Account) {
    if (!offerId) return;
    if (contactsFor === account.id) { setContactsFor(""); return; }
    try { setAccountContacts(await call(`/offers/${offerId}/accounts/${account.id}/contacts`, token)); setContactsFor(account.id); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar os contatos."); }
  }

  async function showSources(account: Account) {
    if (!offerId) return;
    if (sourcesFor === account.id) { setSourcesFor(""); return; }
    try { setAccountSources(await call(`/offers/${offerId}/accounts/${account.id}/sources`, token)); setSourcesFor(account.id); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar as origens."); }
  }

  async function saveActivity(event: FormEvent) {
    event.preventDefault(); if (!offerId || !activityAccount) return;
    setBusy(true); setNotice("");
    try {
      await call(`/offers/${offerId}/accounts/${activityAccount}/activities`, token, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(activity) });
      setActivityAccount(""); setActivity({ activity_type: "contacted", channel: "email", outcome: "", notes: "" }); await loadAccounts(); setNotice("Resultado comercial registrado; status e Engagement Score atualizados.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível registrar o resultado."); }
    finally { setBusy(false); }
  }

  async function downloadCsv() {
    if (!offerId) return;
    try {
      const response = await fetch(`/api/v1/offers/${offerId}/accounts/export`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "Falha ao exportar CSV"); }
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `leadengine360-${offerId.slice(0, 8)}.csv`; anchor.click(); URL.revokeObjectURL(url);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível exportar."); }
  }

  const filtered = accounts;
  if (!token) return <main className="account-empty"><div><h1>Entre para continuar</h1><p>O cadastro da sua empresa precisa estar ativo para consultar as contas.</p><a className="primary" href="/">Voltar ao login <span>→</span></a></div></main>;

  return <main className="workspace"><aside className="sidebar"><div className="brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><div className="side-label">PROSPECÇÃO</div><a className="nav-item" href="/"><span>01</span> Empresa e oferta</a><div className="nav-item active"><span>02</span> Contas e sinais</div><div className="nav-item disabled"><span>03</span> Briefs e exportação</div></aside><section className="main-area"><header className="topbar"><div><span className="crumb">INTELIGÊNCIA COMERCIAL</span><h1>Contas compatíveis com sua oferta</h1></div><div className="account-nav-links"><a className="secondary" href="/integrations">Fontes e conectores</a><a className="secondary" href="/">Editar empresa e ICP</a></div></header><div className="content"><div className="intro"><div className="intro-icon">↗</div><div><h2>Descubra empresas a partir do ICP</h2><p>Configure a fonte integrada e acompanhe as contas encontradas e sua pontuação.</p></div></div>
    {notice && <div className="notice account-notice">{notice}</div>}
    {!offers.length ? <section className="card empty-accounts"><h2>Nenhum ICP aprovado ainda</h2><p>Gere o perfil da oferta, revise os critérios sugeridos e aprove o ICP antes de adicionar contas.</p><a className="primary" href="/">Revisar oferta e ICP <span>→</span></a></section> : <>
      <section className="card import-card"><div className="card-heading"><span className="section-number">01</span><div><h3>Buscar empresas por integração</h3><p>Escolha uma API para buscar empresas a partir do ICP aprovado. OpenStreetMap exige categoria e área; Apollo e Hunter exigem chaves e acesso aos endpoints no servidor.</p></div></div><form className="import-row" onSubmit={startDiscovery}><label className="select-wrap">Oferta<select value={offerId} onChange={(event) => setOfferId(event.target.value)}>{offers.map((offer) => <option key={offer.id} value={offer.id}>{offer.name}</option>)}</select></label><label>Fonte de leads<select value={discoveryProvider} onChange={(event) => setDiscoveryProvider(event.target.value)}><option value="osm-overpass">OpenStreetMap</option><option value="apollo">Apollo.io</option><option value="hunter">Hunter</option></select></label>{discoveryProvider === "osm-overpass" && <><label>Segmento do ICP<select value={segmentLabel} onChange={(event) => setSegmentLabel(event.target.value)}><option value="">Usar categoria da fonte</option>{icpSegments.map((segment) => <option key={segment} value={segment}>{segment}</option>)}</select></label><label>Chave OSM<input required value={osmKey} onChange={(event) => setOsmKey(event.target.value)} placeholder="amenity" /></label><label>Valor da categoria<input required value={osmValue} onChange={(event) => setOsmValue(event.target.value)} placeholder="restaurant" /></label><label>Área: sul, oeste, norte, leste<input required value={bbox} onChange={(event) => setBbox(event.target.value)} placeholder="-23.56, -46.65, -23.55, -46.64" /></label></>}<button className="primary" disabled={busy || !!discoveryJob}>{discoveryJob ? "Buscando…" : "Buscar leads via API →"}</button></form></section>
      <section className="card workflow-card"><div className="accounts-heading"><div><h2>Processamento das contas</h2><p>Acompanhe cada conta após a busca e reexecute as que falharam.</p></div></div>{workflows.length ? <div className="workflow-list">{workflows.map((run) => <div className="workflow-item" key={run.id}><div><b>{run.account_name}</b><small>Estado: {run.status} · tentativas: {run.attempts}</small>{run.error && <small>{run.error}</small>}</div><div className="row-actions"><button className="text-button row-action" onClick={() => void showWorkflow(run)}>Etapas</button>{run.status === "failed" && <button className="secondary" disabled={busy} onClick={() => void retryWorkflow(run)}>Reprocessar</button>}</div>{workflowSteps?.id === run.id && <ul className="workflow-steps">{workflowSteps.steps.map((step) => <li key={step.name}><b>{step.name}</b>: {step.status}{step.error ? ` · ${step.error}` : ""}</li>)}</ul>}</div>)}</div> : <p className="workflow-empty">As contas descobertas aparecerão aqui durante o processamento.</p>}</section>
      <section className="card accounts-card"><div className="accounts-heading"><div><h2>Contas encontradas <span>{totalAccounts}</span></h2><p>Scores explicáveis para esta oferta.</p></div><div className="account-filters"><input placeholder="Buscar empresa, domínio ou setor" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} /><select value={classification} onChange={(event) => { setClassification(event.target.value); setOffset(0); }}><option value="">Todas as classes</option><option>Hot</option><option>Warm</option><option>Target</option><option>Cold</option></select><button className="secondary" onClick={downloadCsv}>Exportar CSV ↓</button></div></div>
      {filtered.length ? <div className="table-scroll"><table><thead><tr><th>Empresa</th><th>Fit</th><th>Intenção</th><th>Engajamento</th><th>Timing</th><th>Total</th><th>Classe</th><th /></tr></thead><tbody>{filtered.map((account) => <tr key={account.id}><td><b>{account.name}</b><small>{account.domain || "Sem domínio"} · {[account.segment, account.employee_band, account.region].filter(Boolean).join(" · ") || "Dados de perfil pendentes"}</small><small>Fit por: {(account.score?.explanation.matched_fit_criteria as string[] | undefined)?.join(", ") || "nenhum critério confirmado"}{account.status ? ` · Etapa: ${account.status}` : ""}</small></td><td>{account.score?.fit ?? 0}/40</td><td>{account.score?.intent ?? 0}/30</td><td>{account.score?.engagement ?? 0}/20</td><td>{account.score?.timing ?? 0}/10</td><td><b>{account.score?.total ?? 0}</b>/100</td><td><span className={`class-pill ${(account.score?.classification || "Cold").toLowerCase()}`}>{account.score?.classification || "Cold"}</span></td><td><div className="row-actions"><button className="text-button row-action" disabled={busy} onClick={() => { setSignalAccount(signalAccount === account.id ? "" : account.id); setActivityAccount(""); setNotice(""); }}>+ Sinal</button><button className="text-button row-action" disabled={busy} onClick={() => showSignals(account)}>Evidências</button><button className="text-button row-action" disabled={busy} onClick={() => showContacts(account)}>Contatos</button><button className="text-button row-action" disabled={busy} onClick={() => showSources(account)}>Origem</button><button className="text-button row-action" disabled={busy} onClick={() => { setActivityAccount(activityAccount === account.id ? "" : account.id); setSignalAccount(""); }}>Resultado</button><button className="text-button row-action" disabled={busy} onClick={() => generateBrief(account)}>Brief</button></div></td></tr>)}</tbody></table></div> : <div className="empty-docs"><span>⌕</span><p>{accounts.length ? "Nenhuma conta corresponde aos filtros." : "Nenhuma conta encontrada para esta oferta."}</p><small>Configure uma busca integrada para descobrir empresas.</small></div>}
      {totalAccounts > 50 && <div className="account-pages"><button className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>← Anterior</button><span>{offset + 1}–{Math.min(offset + 50, totalAccounts)} de {totalAccounts}</span><button className="secondary" disabled={offset + 50 >= totalAccounts} onClick={() => setOffset(offset + 50)}>Próxima →</button></div>}
      {sourcesFor && <div className="evidence-list"><h3>Origens de {accounts.find((account) => account.id === sourcesFor)?.name}</h3>{accountSources.length ? accountSources.map((item) => <article key={`${item.provider_id}-${item.external_id}`}><div><b>{item.provider_id}</b><small>{item.external_id} | consultado em {new Date(item.observed_at).toLocaleDateString("pt-BR")}</small></div>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Abrir registro</a>}</article>) : <p className="muted">Nenhuma origem externa registrada para esta conta.</p>}</div>}
      {contactsFor && <div className="evidence-list"><h3>Contatos de {accounts.find((account) => account.id === contactsFor)?.name}</h3>{accountContacts.length ? accountContacts.map((item) => <article key={item.id}><div><b>{item.kind === "general" ? "Contato geral da empresa" : item.name || "Contato"}</b><small>{item.title || item.source_provider} · confiança {Math.round(item.confidence * 100)}%</small></div><p>{[item.email, item.phone].filter(Boolean).join(" · ")}</p>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Abrir origem ↗</a>}</article>) : <p className="muted">A fonte ainda não informou e-mail ou telefone desta empresa.</p>}</div>}
      {signalsFor && <div className="evidence-list"><h3>Evidências de {accounts.find((account) => account.id === signalsFor)?.name}</h3>{accountSignals.length ? accountSignals.map((item) => <article key={item.id}><div><b>{item.title}</b><small>{new Date(item.occurred_at).toLocaleDateString("pt-BR")} · confiança {Math.round(item.confidence * 100)}%</small></div><p>{item.description}</p>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Abrir fonte ↗</a>}</article>) : <p className="muted">Nenhum sinal registrado para esta conta.</p>}</div>}
      {signalAccount && <form className="signal-form" onSubmit={saveSignal}><div><h3>Registrar evidência comercial</h3><p>Inclua uma fonte e descreva o que foi observado. A pontuação de intenção usa força, confiança e recência.</p></div><div className="signal-fields"><label>Tipo<select value={signal.signal_type} onChange={(event) => setSignal({ ...signal, signal_type: event.target.value })}><option value="hiring">Contratação</option><option value="expansion">Expansão</option><option value="executive_change">Mudança executiva</option><option value="technology">Tecnologia</option><option value="funding">Captação ou aquisição</option><option value="other">Outro</option></select></label><label>Título<input required value={signal.title} onChange={(event) => setSignal({ ...signal, title: event.target.value })} /></label><label>Data do sinal<input type="datetime-local" value={signal.occurred_at} onChange={(event) => setSignal({ ...signal, occurred_at: event.target.value })} /></label><label>Fonte (URL)<input type="url" value={signal.source_url} onChange={(event) => setSignal({ ...signal, source_url: event.target.value })} placeholder="https://..." /></label><label className="signal-wide">Descrição e evidência<textarea required rows={3} value={signal.description} onChange={(event) => setSignal({ ...signal, description: event.target.value, evidence: event.target.value })} /></label><label>Confiança<input type="number" min="0" max="1" step="0.05" value={signal.confidence} onChange={(event) => setSignal({ ...signal, confidence: Number(event.target.value) })} /></label><label>Força (1–5)<input type="number" min="1" max="5" value={signal.strength} onChange={(event) => setSignal({ ...signal, strength: Number(event.target.value) })} /></label></div><div className="signal-actions"><button type="button" className="secondary" onClick={() => setSignalAccount("")}>Cancelar</button><button className="primary" disabled={busy}>Salvar sinal <span>→</span></button></div></form>}
      {activityAccount && <form className="signal-form" onSubmit={saveActivity}><div><h3>Registrar resultado comercial</h3><p>O resultado alimenta o Engagement Score e o histórico da conta.</p></div><div className="signal-fields"><label>Resultado<select value={activity.activity_type} onChange={(event) => setActivity({ ...activity, activity_type: event.target.value as NewActivity["activity_type"] })}><option value="contacted">Contato realizado</option><option value="replied">Respondeu</option><option value="meeting">Reunião marcada</option><option value="opportunity">Oportunidade criada</option><option value="won">Venda ganha</option><option value="lost">Venda perdida</option></select></label><label>Canal<input value={activity.channel} onChange={(event) => setActivity({ ...activity, channel: event.target.value })} placeholder="e-mail, ligação, indicação…" /></label><label className="signal-wide">Observações<textarea rows={2} value={activity.notes} onChange={(event) => setActivity({ ...activity, notes: event.target.value })} placeholder="Contexto útil sobre o resultado" /></label></div><div className="signal-actions"><button type="button" className="secondary" onClick={() => setActivityAccount("")}>Cancelar</button><button className="primary" disabled={busy}>Salvar resultado <span>→</span></button></div></form>}
      </section>{brief && <section className="card brief-card"><div className="accounts-heading"><div><span className="eyebrow">BRIEF COMERCIAL · {brief.generated_with}</span><h2>{brief.account}</h2></div><div className="row-actions"><button className="secondary" disabled={busy} onClick={() => void generateBrief({ id: brief.account_id, name: brief.account }, true)}>Regenerar</button><button className="secondary" onClick={() => setBrief(null)}>Fechar</button></div></div><p className="review-note">Revise os fatos e as hipóteses antes de usar a sugestão em uma abordagem.</p><pre>{JSON.stringify(brief.data, null, 2)}</pre></section>}</>}
      <footer className="page-foot">LeadEngine360 <span>·</span> A evidência orienta a prioridade. Contas da fonte OSM: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors · ODbL</a>.</footer></div></section></main>;
}
