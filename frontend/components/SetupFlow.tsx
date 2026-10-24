"use client";
import { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";
import SearchField from "@/components/ui/SearchField";
import SegmentedControl from "@/components/ui/SegmentedControl";
import type { CatalogApi, Selection } from "@/lib/types";

const STEPS = ["role", "level", "company", "topic"] as const;
type Step = (typeof STEPS)[number];

export function canStart(s: Selection): boolean {
  return Boolean(s.profile && s.level);
}

type Props = { api: CatalogApi; onStart: (selection: Selection) => void; starting?: boolean };

export default function SetupFlow({ api, onStart, starting = false }: Props) {
  const [step, setStep] = useState<Step>("role");
  const [sel, setSel] = useState<Selection>({});
  const [profiles, setProfiles] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [companies, setCompanies] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);

  useEffect(() => {
    api.profiles().then(setProfiles);
    api.levels().then(setLevels);
  }, [api]);

  useEffect(() => {
    if (!query.trim()) return setCompanies([]);
    const id = setTimeout(() => api.companies(query.trim()).then(setCompanies), 150);
    return () => clearTimeout(id);
  }, [api, query]);

  useEffect(() => {
    if (step === "topic" && sel.profile) api.topics(sel.profile, sel.company).then(setTopics);
  }, [api, step, sel.profile, sel.company]);

  const next = () => setStep(STEPS[STEPS.indexOf(step) + 1]);
  const back = () => setStep(STEPS[STEPS.indexOf(step) - 1]);

  return (
    <section className="mx-auto flex min-h-[80vh] max-w-xl flex-col items-center justify-center gap-8 px-4 text-center">
      {step === "role" ? (
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Practice your next interview.</h1>
      ) : (
        <h2 className="text-3xl font-semibold tracking-tight">
          {{ level: "Which level?", company: "Which company?", topic: "Any topic in mind?" }[step]}
        </h2>
      )}

      {step === "role" && (
        <div className="flex flex-wrap justify-center gap-2">
          {profiles.map((p) => (
            <Chip key={p} selected={sel.profile === p} onClick={() => { setSel({ profile: p }); next(); }}>{p}</Chip>
          ))}
        </div>
      )}

      {step === "level" && (
        <SegmentedControl options={levels} value={sel.level} onChange={(level) => { setSel({ ...sel, level }); next(); }} />
      )}

      {step === "company" && (
        <div className="flex w-full flex-col items-center gap-4">
          <SearchField placeholder="Search companies" value={query} onChange={(e) => setQuery(e.target.value)} />
          <div className="flex flex-wrap justify-center gap-2">
            {companies.map((c) => (
              <Chip key={c} onClick={() => { setSel({ ...sel, company: c }); next(); }}>{c}</Chip>
            ))}
          </div>
          <Button variant="ghost" onClick={() => { setSel({ ...sel, company: undefined }); next(); }}>Skip</Button>
        </div>
      )}

      {step === "topic" && (
        <div className="flex flex-col items-center gap-6">
          <div className="flex flex-wrap justify-center gap-2">
            {topics.map((t) => (
              <Chip key={t} selected={sel.topic === t} onClick={() => setSel({ ...sel, topic: sel.topic === t ? undefined : t })}>{t}</Chip>
            ))}
          </div>
          <Button
            disabled={!canStart(sel) || starting}
            onClick={() => onStart({ profile: sel.profile, level: sel.level, company: sel.company, topic: sel.topic })}
          >
            {starting ? "Starting…" : "Start"}
          </Button>
        </div>
      )}

      {step !== "role" && <Button variant="ghost" onClick={back}>Back</Button>}
    </section>
  );
}
