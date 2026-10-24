"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";
import { api } from "@/lib/api";
import { rememberSession } from "@/lib/session";
import { useLoad } from "@/lib/useLoad";
import { Button, Chip, SearchField, SegmentedControl, StatusLine, enter } from "@/components/ui";

type Step = "role" | "level" | "company" | "topic";
const STEPS: Step[] = ["role", "level", "company", "topic"];

const TITLES: Record<Step, string> = {
  role: "Choose your role.",
  level: "Choose your level.",
  company: "Choose a company.",
  topic: "Choose a topic.",
};

const MAX_COMPANY_RESULTS = 8;
const MAX_TOPIC_CHIPS = 12;
const SEARCH_DEBOUNCE_MS = 200;

export function SetupFlow() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [step, setStep] = useState<Step>("role");
  const [profile, setProfile] = useState<string | null>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [company, setCompany] = useState<string | null>(null);
  // undefined = not chosen yet, null = "Any topic"
  const [topic, setTopic] = useState<string | null | undefined>(undefined);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState(false);

  const index = STEPS.indexOf(step);
  const next = () => setStep(STEPS[Math.min(index + 1, STEPS.length - 1)]);
  const back = () => setStep(STEPS[Math.max(index - 1, 0)]);

  const canStart = Boolean(profile && level && topic !== undefined) && !starting;

  async function start() {
    if (!profile || !level || topic === undefined) return;
    setStarting(true);
    setStartError(false);
    try {
      const session = await api.createSession({ profile, level, company, topic });
      rememberSession(session);
      router.push(`/interview/${encodeURIComponent(session.session_id)}`);
    } catch {
      setStartError(true);
      setStarting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-[100dvh] w-full max-w-content flex-col px-6 pb-10 pt-[12vh]">
      <h1 className="text-display text-fg">Practice your next interview.</h1>

      <div className="mt-10 flex min-h-tap items-center">
        {index > 0 ? (
          <Button variant="plain" className="-ml-4" onClick={back} aria-label="Back">
            <svg aria-hidden viewBox="0 0 12 20" className="h-4 w-3" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 2L2 10l8 8" />
            </svg>
            Back
          </Button>
        ) : null}
      </div>

      <motion.section
        key={step}
        initial={reduce ? false : enter.initial}
        animate={enter.animate}
        transition={enter.transition}
        className="mt-2 flex flex-1 flex-col"
        aria-labelledby="step-title"
      >
        <p id="step-title" className="mb-6 text-body text-muted">
          {TITLES[step]}
        </p>

        {step === "role" && (
          <RoleStep
            value={profile}
            onPick={(p) => {
              if (p !== profile) setTopic(undefined);
              setProfile(p);
              next();
            }}
          />
        )}
        {step === "level" && (
          <LevelStep
            value={level}
            onPick={(l) => {
              setLevel(l);
              next();
            }}
          />
        )}
        {step === "company" && (
          <CompanyStep
            value={company}
            onPick={(c) => {
              setCompany(c);
              next();
            }}
          />
        )}
        {step === "topic" && profile && (
          <TopicStep profile={profile} value={topic} onPick={setTopic} />
        )}

        {step === "topic" && (
          <div className="mt-auto flex flex-col items-center gap-3 pt-10">
            {startError && <p className="text-body text-muted">Couldn’t start the interview.</p>}
            <Button className="w-full sm:w-auto sm:min-w-[200px]" disabled={!canStart} onClick={start}>
              {starting ? "Starting…" : "Start"}
            </Button>
          </div>
        )}
      </motion.section>
    </main>
  );
}

function RoleStep({ value, onPick }: { value: string | null; onPick: (v: string) => void }) {
  const roles = useLoad(() => api.profiles(), "profiles");
  if (roles.loading) return <StatusLine text="Loading…" className="items-start text-left" />;
  if (roles.error) return <StatusLine text="Couldn’t load roles." action={{ label: "Try again", onClick: roles.retry }} />;
  if (!roles.data?.length) return <StatusLine text="No roles yet." action={{ label: "Try again", onClick: roles.retry }} />;
  return (
    <div className="flex flex-wrap gap-3">
      {roles.data.map((r) => (
        <Chip key={r} selected={r === value} onClick={() => onPick(r)}>
          {r}
        </Chip>
      ))}
    </div>
  );
}

function LevelStep({ value, onPick }: { value: string | null; onPick: (v: string) => void }) {
  const levels = useLoad(() => api.levels(), "levels");
  if (levels.loading) return <StatusLine text="Loading…" className="items-start text-left" />;
  if (levels.error) return <StatusLine text="Couldn’t load levels." action={{ label: "Try again", onClick: levels.retry }} />;
  return <SegmentedControl label="Level" options={levels.data ?? []} value={value} onChange={onPick} />;
}

function CompanyStep({ value, onPick }: { value: string | null; onPick: (v: string | null) => void }) {
  const [query, setQuery] = useState(value ?? "");
  const [debounced, setDebounced] = useState(query.trim());

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [query]);

  const results = useLoad(() => api.companies(debounced), `companies:${debounced}`, debounced.length > 0);
  const shown = debounced.length > 0 ? (results.data ?? []).slice(0, MAX_COMPANY_RESULTS) : [];

  return (
    <div className="flex flex-1 flex-col">
      <SearchField label="Search companies" value={query} onChange={setQuery} autoFocus />
      <div className="mt-5 min-h-[56px]">
        {debounced.length > 0 && !results.loading && results.error ? (
          <p className="text-body text-muted">Couldn’t search companies.</p>
        ) : debounced.length > 0 && !results.loading && shown.length === 0 && results.data ? (
          <p className="text-body text-muted">No companies match.</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {shown.map((c) => (
              <Chip key={c} selected={c === value} onClick={() => onPick(c)}>
                {c}
              </Chip>
            ))}
          </div>
        )}
      </div>
      <div className="mt-auto flex justify-center pt-10">
        <Button variant="secondary" onClick={() => onPick(null)}>
          Skip
        </Button>
      </div>
    </div>
  );
}

function TopicStep({
  profile,
  value,
  onPick,
}: {
  profile: string;
  value: string | null | undefined;
  onPick: (v: string | null) => void;
}) {
  const topics = useLoad(() => api.topics(profile), `topics:${profile}`);
  const [filter, setFilter] = useState("");
  const all = useMemo(() => topics.data ?? [], [topics.data]);
  const needsFilter = all.length > MAX_TOPIC_CHIPS;

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase();
    const matches = f ? all.filter((t) => t.toLowerCase().includes(f)) : all;
    const list = matches.slice(0, MAX_TOPIC_CHIPS);
    // Keep the current choice visible even when it is filtered out.
    if (value && !list.includes(value)) list.unshift(value);
    return list;
  }, [all, filter, value]);

  return (
    <div className="flex flex-col gap-5">
      {needsFilter && <SearchField label="Filter topics" value={filter} onChange={setFilter} />}
      <div className="flex flex-wrap gap-3">
        <Chip selected={value === null} onClick={() => onPick(null)}>
          Any topic
        </Chip>
        {!topics.loading &&
          !topics.error &&
          visible.map((t) => (
            <Chip key={t} selected={t === value} onClick={() => onPick(t)}>
              {t}
            </Chip>
          ))}
      </div>
      {topics.loading && <p className="text-body text-muted">Loading…</p>}
      {topics.error ? <StatusLine text="Couldn’t load topics." action={{ label: "Try again", onClick: topics.retry }} className="items-start text-left" /> : null}
    </div>
  );
}
