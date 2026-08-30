import EvaluationCenter from "../features/evaluation/EvaluationCenter";
import EvaluationRunView from "../features/evaluation/EvaluationRunView";
import { useParams } from "react-router-dom";

export default function Evaluation() {
  const { runId } = useParams();
  const parsed = runId ? Number(runId) : null;
  return parsed && Number.isInteger(parsed) ? <EvaluationRunView runId={parsed} /> : <EvaluationCenter />;
}
