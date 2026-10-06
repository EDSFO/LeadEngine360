"use client";

import { FormEvent, useEffect, useState } from "react";
import "../styles.css";
import "../team/team.css";

export default function JoinPage() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setToken(new URLSearchParams(window.location.search).get("token") || ""); }, []);

  async function accept(event: FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    try {
      const response = await fetch("/api/v1/auth/accept-invitation", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }) });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || "Não foi possível aceitar o convite.");
      window.localStorage.setItem("le360_token", body.access_token);
      window.location.assign("/");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível aceitar o convite."); }
    finally { setBusy(false); }
  }

  return <main className="team-page"><header><a href="/">← Voltar ao LeadEngine360</a><h1>Entrar na equipe</h1><p>Defina sua senha para aceitar o convite.</p></header>{notice && <div className="notice">{notice}</div>}{!token ? <p>O link do convite está incompleto.</p> : <section className="card"><form onSubmit={accept}><label>Senha<input type="password" minLength={10} required value={password} onChange={(event) => setPassword(event.target.value)} /></label><button className="primary" disabled={busy}>Aceitar convite</button></form></section>}</main>;
}
