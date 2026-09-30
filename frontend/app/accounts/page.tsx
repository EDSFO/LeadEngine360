"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import "../styles.css";
import "./accounts.css";
import "./evidence.css";

type Offer = { id: string; name: string };
type Score = { fit: number; intent: number; engagement: number; timing: number; total: number; classification: string; explanation: Record<string, unknown> };
type Account = { id: string; name: string; domain: string | null; segment: string | null; employee_band: string | null; region: string | null; status?: string; score: Score | null };
type NewSignal = { signal_type: string; title: string; description: string; source_url: string; evidence: string; occurred_at: string; confidence: number; strength: number };
type NewActivity = { activity_type: "contacted" | "replied" | "meeting" | "opportunity" | "won" | "lost"; channel: string; outcome: string; notes: string };
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
  const [classification, setClassification] = useState("");
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [signalAccount, setSignalAccount] = useState("");
  const [signal, setSignal] = useState<NewSignal>(blankSignal);
  const [activityAccount, setActivityAccount] = useState("");
  const [activity, setActivity] = useState<NewActivity>({ activity_type: "contacted", channel: "email", outcome: "", notes: "" });
  const [brief, setBrief] = useState<{ account: string; generated_with: string; data: Record<string, unknown> } | null>(null);
  const [signalsFor, setSignalsFor] = useState<string>("");
  const [accountSignals, setAccountSignals] = useState<{ id: string; title: string; description: string; source_url: string | null; occurred_at: string; confidence: number }[]>([]);

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
      const result = await call(`/offers/${offerId}/accounts?limit=500`, token);
      setAccounts(result.items);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar as contas."); }
  }, [token, offerId]);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  async function importCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file || !offerId) return;
    setBusy(true); setNotice("");
    try {
      const data = new FormData(); data.append("file", file);
      const result = await call(`/offers/${offerId}/accounts/import`, token, { method: "POST", body: data });
      await loadAccounts();
      setNotice(`Importação concluída: ${result.created} novas, ${result.updated} atualizadas, ${result.skipped} ignoradas.${result.errors?.length ? ` Primeiros erros: ${result.errors.map((item: { row: number; reason: string }) => `linha ${item.row}: ${item.reason}`).join("; ")}` : ""}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível importar o CSV."); }
    finally { setBusy(false); event.target.value = ""; }
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

  async function generateBrief(account: Account) {
    if (!offerId) return;
    setBusy(true); setNotice("");
    try {
      const result = await call(`/offers/${offerId}/accounts/${account.id}/brief`, token, { method: "POST" });
      setBrief({ account: account.name, generated_with: result.generated_with, data: result.brief });
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível gerar o brief."); }
    finally { setBusy(false); }
  }

  async function showSignals(account: Account) {
    if (!offerId) return;
    if (signalsFor === account.id) { setSignalsFor(""); return; }
    try { setAccountSignals(await call(`/offers/${offerId}/accounts/${account.id}/signals`, token)); setSignalsFor(account.id); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível carregar as evidências."); }
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

  const filtered = accounts.filter((account) => (!classification || account.score?.classification === classification) && (!search || `${account.name} ${account.domain || ""} ${account.segment || ""}`.toLowerCase().includes(search.toLowerCase())));
  if (!token) return <main className="account-empty"><div><h1>Entre para continuar</h1><p>O cadastro da sua empresa precisa estar ativo para consultar as contas.</p><a className="primary" href="/">Voltar ao login <span>→</span></a></div></main>;

  return <main className="workspace"><aside className="sidebar"><div className="brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><div className="side-label">PROSPECÇÃO</div><a className="nav-item" href="/"><span>01</span> Empresa e oferta</a><div className="nav-item active"><span>02</span> Contas e sinais</div><div className="nav-item disabled"><span>03</span> Briefs e exportação</div></aside><section className="main-area"><header className="topbar"><div><span className="crumb">INTELIGÊNCIA COMERCIAL</span><h1>Contas compatíveis com sua oferta</h1></div><div className="account-nav-links"><a className="secondary" href="/integrations">Fontes e conectores</a><a className="secondary" href="/">Editar empresa e ICP</a></div></header><div className="content"><div className="intro"><div className="intro-icon">↗</div><div><h2>Comece com uma lista de empresas</h2><p>Importe contas para o ICP aprovado. O sistema calcula aderência e você pode adicionar sinais com origem e evidência.</p></div></div>
    {notice && <div className="notice account-notice">{notice}</div>}
    {!offers.length ? <section className="card empty-accounts"><h2>Nenhum ICP aprovado ainda</h2><p>Gere o perfil da oferta, revise os critérios sugeridos e aprove o ICP antes de adicionar contas.</p><a className="primary" href="/">Revisar oferta e ICP <span>→</span></a></section> : <>
      <section className="card import-card"><div className="card-heading"><span className="section-number">01</span><div><h3>Importar empresas</h3><p>CSV com colunas: empresa, domínio, segmento, porte e região. Domínio ajuda a reconhecer registros repetidos.</p></div></div><div className="import-row"><label className="select-wrap">Oferta<select value={offerId} onChange={(event) => setOfferId(event.target.value)}>{offers.map((offer) => <option key={offer.id} value={offer.id}>{offer.name}</option>)}</select></label><label className={`upload-button ${busy ? "disabled-button" : ""}`}>＋ Selecionar CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={importCsv} /></label><a className="template-link" href="data:text/csv;charset=utf-8,%EF%BB%BFempresa%2Cdominio%2Csegmento%2Cporte%2Cregiao%0AAcme%20Exemplo%2Cacme.com.br%2CTecnologia%2C51-200%2CBrasil" download="modelo-contas-leadengine360.csv">Baixar modelo CSV</a></div></section>
      <section className="card accounts-card"><div className="accounts-heading"><div><h2>Contas importadas <span>{accounts.length}</span></h2><p>Scores explicáveis para esta oferta.</p></div><div className="account-filters"><input placeholder="Buscar empresa, domínio ou setor" value={search} onChange={(event) => setSearch(event.target.value)} /><select value={classification} onChange={(event) => setClassification(event.target.value)}><option value="">Todas as classes</option><option>Hot</option><option>Warm</option><option>Target</option><option>Cold</option></select><button className="secondary" onClick={downloadCsv}>Exportar CSV ↓</button></div></div>
      {filtered.length ? <div className="table-scroll"><table><thead><tr><th>Empresa</th><th>Fit</th><th>Intenção</th><th>Engajamento</th><th>Timing</th><th>Total</th><th>Classe</th><th /></tr></thead><tbody>{filtered.map((account) => <tr key={account.id}><td><b>{account.name}</b><small>{account.domain || "Sem domínio"} · {[account.segment, account.employee_band, account.region].filter(Boolean).join(" · ") || "Dados de perfil pendentes"}</small><small>Fit por: {(account.score?.explanation.matched_fit_criteria as string[] | undefined)?.join(", ") || "nenhum critério confirmado"}{account.status ? ` · Etapa: ${account.status}` : ""}</small></td><td>{account.score?.fit ?? 0}/40</td><td>{account.score?.intent ?? 0}/30</td><td>{account.score?.engagement ?? 0}/20</td><td>{account.score?.timing ?? 0}/10</td><td><b>{account.score?.total ?? 0}</b>/100</td><td><span className={`class-pill ${(account.score?.classification || "Cold").toLowerCase()}`}>{account.score?.classification || "Cold"}</span></td><td><div className="row-actions"><button className="text-button row-action" disabled={busy} onClick={() => { setSignalAccount(signalAccount === account.id ? "" : account.id); setActivityAccount(""); setNotice(""); }}>+ Sinal</button><button className="text-button row-action" disabled={busy} onClick={() => showSignals(account)}>Evidências</button><button className="text-button row-action" disabled={busy} onClick={() => { setActivityAccount(activityAccount === account.id ? "" : account.id); setSignalAccount(""); }}>Resultado</button><button className="text-button row-action" disabled={busy} onClick={() => generateBrief(account)}>Brief</button></div></td></tr>)}</tbody></table></div> : <div className="empty-docs"><span>⌕</span><p>{accounts.length ? "Nenhuma conta corresponde aos filtros." : "Nenhuma conta importada para esta oferta."}</p><small>Importe um CSV com as empresas que deseja priorizar.</small></div>}
      {signalsFor && <div className="evidence-list"><h3>Evidências de {accounts.find((account) => account.id === signalsFor)?.name}</h3>{accountSignals.length ? accountSignals.map((item) => <article key={item.id}><div><b>{item.title}</b><small>{new Date(item.occurred_at).toLocaleDateString("pt-BR")} · confiança {Math.round(item.confidence * 100)}%</small></div><p>{item.description}</p>{item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">Abrir fonte ↗</a>}</article>) : <p className="muted">Nenhum sinal registrado para esta conta.</p>}</div>}
      {signalAccount && <form className="signal-form" onSubmit={saveSignal}><div><h3>Registrar evidência comercial</h3><p>Inclua uma fonte e descreva o que foi observado. A pontuação de intenção usa força, confiança e recência.</p></div><div className="signal-fields"><label>Tipo<select value={signal.signal_type} onChange={(event) => setSignal({ ...signal, signal_type: event.target.value })}><option value="hiring">Contratação</option><option value="expansion">Expansão</option><option value="executive_change">Mudança executiva</option><option value="technology">Tecnologia</option><option value="funding">Captação ou aquisição</option><option value="other">Outro</option></select></label><label>Título<input required value={signal.title} onChange={(event) => setSignal({ ...signal, title: event.target.value })} /></label><label>Data do sinal<input type="datetime-local" value={signal.occurred_at} onChange={(event) => setSignal({ ...signal, occurred_at: event.target.value })} /></label><label>Fonte (URL)<input type="url" value={signal.source_url} onChange={(event) => setSignal({ ...signal, source_url: event.target.value })} placeholder="https://..." /></label><label className="signal-wide">Descrição e evidência<textarea required rows={3} value={signal.description} onChange={(event) => setSignal({ ...signal, description: event.target.value, evidence: event.target.value })} /></label><label>Confiança<input type="number" min="0" max="1" step="0.05" value={signal.confidence} onChange={(event) => setSignal({ ...signal, confidence: Number(event.target.value) })} /></label><label>Força (1–5)<input type="number" min="1" max="5" value={signal.strength} onChange={(event) => setSignal({ ...signal, strength: Number(event.target.value) })} /></label></div><div className="signal-actions"><button type="button" className="secondary" onClick={() => setSignalAccount("")}>Cancelar</button><button className="primary" disabled={busy}>Salvar sinal <span>→</span></button></div></form>}
      {activityAccount && <form className="signal-form" onSubmit={saveActivity}><div><h3>Registrar resultado comercial</h3><p>O resultado alimenta o Engagement Score e o histórico da conta.</p></div><div className="signal-fields"><label>Resultado<select value={activity.activity_type} onChange={(event) => setActivity({ ...activity, activity_type: event.target.value as NewActivity["activity_type"] })}><option value="contacted">Contato realizado</option><option value="replied">Respondeu</option><option value="meeting">Reunião marcada</option><option value="opportunity">Oportunidade criada</option><option value="won">Venda ganha</option><option value="lost">Venda perdida</option></select></label><label>Canal<input value={activity.channel} onChange={(event) => setActivity({ ...activity, channel: event.target.value })} placeholder="e-mail, ligação, indicação…" /></label><label className="signal-wide">Observações<textarea rows={2} value={activity.notes} onChange={(event) => setActivity({ ...activity, notes: event.target.value })} placeholder="Contexto útil sobre o resultado" /></label></div><div className="signal-actions"><button type="button" className="secondary" onClick={() => setActivityAccount("")}>Cancelar</button><button className="primary" disabled={busy}>Salvar resultado <span>→</span></button></div></form>}
      </section>{brief && <section className="card brief-card"><div className="accounts-heading"><div><span className="eyebrow">BRIEF COMERCIAL · {brief.generated_with}</span><h2>{brief.account}</h2></div><button className="secondary" onClick={() => setBrief(null)}>Fechar</button></div><p className="review-note">Revise os fatos e as hipóteses antes de usar a sugestão em uma abordagem.</p><pre>{JSON.stringify(brief.data, null, 2)}</pre></section>}</>}
      <footer className="page-foot">LeadEngine360 <span>·</span> A evidência orienta a prioridade.</footer></div></section></main>;
}
