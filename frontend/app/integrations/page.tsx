"use client";

import { useEffect, useMemo, useState } from "react";
import "../styles.css";
import "./integrations.css";

type Provider = { id: string; stage: string; name: string; providers: string; type: string; status: "available" | "planned"; description: string };
type Offer = { id: string; name: string };

async function api(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}` } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Não foi possível concluir a solicitação.");
  return body;
}

export default function IntegrationsPage() {
  const [token, setToken] = useState("");
  const [offers, setOffers] = useState<Offer[]>([]);
  const [offerId, setOfferId] = useState("");
  const [catalog, setCatalog] = useState<Provider[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { const saved = window.localStorage.getItem("le360_token"); if (saved) setToken(saved); }, []);
  useEffect(() => {
    if (!token) return;
    Promise.all([api("/onboarding", token), api("/integrations/catalog", token)])
      .then(([company, sources]) => {
        setOffers(company?.offers || []);
        setOfferId(company?.offers?.[0]?.id || "");
        setCatalog(sources.items || []);
      }).catch((error) => setNotice(error.message));
  }, [token]);
  useEffect(() => {
    if (!token || !offerId) return;
    api(`/offers/${offerId}/integrations`, token).then((result) => setSelected(result.provider_ids || []))
      .catch((error) => setNotice(error.message));
  }, [token, offerId]);

  const stages = useMemo(() => [...new Set(catalog.map((item) => item.stage))], [catalog]);
  function toggle(id: string) { setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  async function save() {
    if (!offerId) return;
    setBusy(true); setNotice("");
    try {
      await api(`/offers/${offerId}/integrations`, token, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider_ids: selected }) });
      setNotice("Preferências desta oferta foram salvas. Os itens marcados como planejados ainda precisam de implementação e configuração.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Falha ao salvar as preferências."); }
    finally { setBusy(false); }
  }

  if (!token) return <main className="account-empty"><div><h1>Entre para continuar</h1><p>Faça login para configurar as fontes da sua oferta.</p><a className="primary" href="/">Voltar ao login <span>→</span></a></div></main>;
  return <main className="workspace"><aside className="sidebar"><div className="brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><div className="side-label">PROSPECÇÃO</div><a className="nav-item" href="/"><span>01</span> Empresa, oferta e ICP</a><a className="nav-item" href="/accounts"><span>02</span> Contas e sinais</a><div className="nav-item active"><span>03</span> Fontes e conectores</div></aside><section className="main-area"><header className="topbar"><div><span className="crumb">CONFIGURAÇÃO DO PROCESSO</span><h1>Fontes e conectores</h1></div><a className="secondary" href="/accounts">Voltar às contas</a></header><div className="content integration-content"><div className="intro"><div className="intro-icon">↗</div><div><h2>Monte o fluxo de inteligência da sua oferta</h2><p>O catálogo traduz as etapas do diagrama em fontes e ferramentas. Selecione o que pretende usar; cada conector mostra se já está disponível no MVP ou está planejado.</p></div></div>
    {notice && <div className="notice integration-notice">{notice}</div>}
    {offers.length > 0 && <section className="integration-toolbar"><label className="select-wrap">Oferta<select value={offerId} onChange={(event) => setOfferId(event.target.value)}>{offers.map((offer) => <option key={offer.id} value={offer.id}>{offer.name}</option>)}</select></label><div className="legend"><span className="available-dot" /> Disponível no MVP <span className="planned-dot" /> Planejado</div></section>}
    {!offers.length ? <section className="card"><h2>Cadastre uma oferta primeiro</h2><a href="/" className="primary">Configurar empresa e oferta <span>→</span></a></section> : stages.map((stage, index) => <section className="card integration-stage" key={stage}><div className="card-heading"><span className="section-number">{String(index + 1).padStart(2, "0")}</span><div><h3>{stage}</h3><p>Ferramentas e fontes relacionadas a esta etapa do processo.</p></div></div><div className="provider-grid">{catalog.filter((item) => item.stage === stage).map((item) => <label className={`provider-card ${selected.includes(item.id) ? "provider-selected" : ""}`} key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} /><span className="provider-main"><b>{item.name}</b><small>{item.providers}</small></span><span className={`provider-status ${item.status}`}>{item.status === "available" ? "Disponível" : "Planejado"}</span><span className="provider-description">{item.description}</span></label>)}</div></section>)}
    {offers.length > 0 && <div className="integration-save"><p>Chaves e tokens de fornecedores não são coletados nem armazenados nesta tela.</p><button className="primary" onClick={save} disabled={busy}>{busy ? "Salvando…" : "Salvar seleção"}<span>→</span></button></div>}
    <footer className="page-foot">LeadEngine360 <span>·</span> Conectores por oferta</footer></div></section></main>;
}
