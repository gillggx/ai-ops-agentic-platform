import Playbook from "@/components/skills/Playbook";

export const metadata = { title: "Skill · Author · AIOps Playbook" };

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <Playbook slug={slug} mode="author"/>;
}
