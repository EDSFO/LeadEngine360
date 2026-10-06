"use client";

import { useEffect, useMemo, useState } from "react";

type Props = { draft: string; onChange: (value: string) => void };
const fields = [
  ["segments", "Segmentos"],
  ["company_size", "Portes de empresa"],
  ["regions", "Regiões"],
] as const;
const listFields = [...fields, ["buyer_roles", "Cargos envolvidos"], ["exclusions", "Exclusões"]] as const;

function parsedDraft(draft: string): Record<string, unknown> | null {
  try { const value = JSON.parse(draft); return value && typeof value === "object" && !Array.isArray(value) ? value : null; }
  catch { return null; }
}

export default function IcpEditor({ draft, onChange }: Props) {
  const profile = useMemo(() => parsedDraft(draft), [draft]);
  const criteria = profile?.ideal_customer_profile && typeof profile.ideal_customer_profile === "object" ? profile.ideal_customer_profile as Record<string, unknown> : {};
  const weights = criteria.weights && typeof criteria.weights === "object" ? criteria.weights as Record<string, unknown> : {};
  const thresholds = profile?.classification_thresholds && typeof profile.classification_thresholds === "object" ? profile.classification_thresholds as Record<string, unknown> : {};
  const required = Array.isArray(criteria.required) ? criteria.required as string[] : [];
  const [texts, setTexts] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!profile) return;
    const current = profile.ideal_customer_profile && typeof profile.ideal_customer_profile === "object" ? profile.ideal_customer_profile as Record<string, unknown> : {};
    setTexts(Object.fromEntries(listFields.map(([key]) => [key, Array.isArray(current[key]) ? (current[key] as string[]).join(", ") : ""])));
  }, [draft]);

  function updateCriteria(key: string, value: unknown) {
    if (!profile) return;
    onChange(JSON.stringify({ ...profile, ideal_customer_profile: { ...criteria, [key]: value } }, null, 2));
  }

  function commitList(key: string) {
    const values = (texts[key] || "").split(/[,;\n]/).map((item) => item.trim()).filter(Boolean);
    updateCriteria(key, [...new Set(values)]);
  }

  function updateThreshold(key: string, value: number) {
    if (!profile || !Number.isFinite(value)) return;
    onChange(JSON.stringify({ ...profile, classification_thresholds: { ...thresholds, [key]: value } }, null, 2));
  }

  if (!profile) return <p className="muted">Corrija o JSON para voltar a editar os critérios pelo formulário.</p>;

  return <div className="icp-editor"><h3>Critérios de aderência</h3><p className="muted">Separe valores por vírgula. Marque como obrigatório apenas um critério que não pode faltar na conta.</p><div className="icp-grid">
    {listFields.map(([key, label]) => <label key={key}>{label}<input value={texts[key] || ""} onChange={(event) => setTexts((current) => ({ ...current, [key]: event.target.value }))} onBlur={() => commitList(key)} placeholder={key === "segments" ? "Ex.: restaurantes, hotéis" : key === "regions" ? "Ex.: São Paulo" : "Separe por vírgulas"} /></label>)}
  </div><h3>Pesos e obrigatoriedade</h3><div className="icp-grid">{fields.map(([key, label]) => <div className="icp-rule" key={key}><label>{label} — peso<input type="number" min="0.1" step="0.1" value={typeof weights[key] === "number" ? weights[key] as number : 1} onChange={(event) => updateCriteria("weights", { ...weights, [key]: Number(event.target.value) })} /></label><label className="icp-check"><input type="checkbox" checked={required.includes(key)} onChange={(event) => updateCriteria("required", event.target.checked ? [...required, key] : required.filter((item) => item !== key))} />Obrigatório</label></div>)}</div>
    <h3>Limiares de classificação</h3><div className="icp-grid">{([["target", "Target", 40], ["warm", "Warm", 60], ["hot", "Hot", 80], ["minimum_hot_fit", "Fit mínimo para Hot", 24]] as const).map(([key, label, fallback]) => <label key={key}>{label}<input type="number" min="0" max="100" value={typeof thresholds[key] === "number" ? thresholds[key] as number : fallback} onChange={(event) => updateThreshold(key, Number(event.target.value))} /></label>)}</div>
  </div>;
}
