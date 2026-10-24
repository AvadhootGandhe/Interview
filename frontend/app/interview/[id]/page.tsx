import { InterviewScreen } from "@/components/interview/InterviewScreen";

export default async function InterviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InterviewScreen id={decodeURIComponent(id)} />;
}
