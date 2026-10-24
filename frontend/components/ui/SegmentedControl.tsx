type Props = { options: string[]; value?: string; onChange: (value: string) => void };

export default function SegmentedControl({ options, value, onChange }: Props) {
  return (
    <div role="group" className="flex flex-wrap justify-center gap-1 rounded-control bg-surface p-1">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
          className={`rounded-[11px] px-4 py-2 text-[15px] transition ${option === value ? "bg-bg text-ink shadow-sm" : "text-muted hover:text-ink"}`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
