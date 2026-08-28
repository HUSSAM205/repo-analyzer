"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Brain, Check, Loader2, RotateCcw, X } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { QuizQuestion, QuizResponse } from "@/lib/types";

type Status = "idle" | "loading" | "success" | "error";

export function KnowledgeQuiz({ repoId }: { repoId: string }) {
  const [status, setStatus] = useState<Status>("idle");
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);

  async function start() {
    setStatus("loading");
    setError(null);
    try {
      const res = await apiFetch(`/api/repos/${repoId}/quiz`, { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: undefined }));
        setError(body.detail ?? "Could not generate the quiz.");
        setStatus("error");
        return;
      }
      const data = (await res.json()) as QuizResponse;
      setQuestions(data.questions);
      setAnswers(new Array(data.questions.length).fill(null));
      setStatus("success");
    } catch {
      setError("Could not reach the server.");
      setStatus("error");
    }
  }

  function selectAnswer(qIndex: number, optionIndex: number) {
    setAnswers((prev) => {
      if (prev[qIndex] !== null) return prev; // already answered -- locked in
      const next = [...prev];
      next[qIndex] = optionIndex;
      return next;
    });
  }

  function retake() {
    setAnswers(new Array(questions.length).fill(null));
  }

  const answeredCount = answers.filter((a) => a !== null).length;
  const correctCount = answers.filter((a, i) => a !== null && a === questions[i]?.correct_index).length;
  const allAnswered = questions.length > 0 && answeredCount === questions.length;

  if (status === "idle") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <Brain className="h-8 w-8 text-primary" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          Test your understanding of this repo with 3 quick multiple-choice questions.
        </p>
        <Button onClick={start}>Start Quiz</Button>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <motion.span animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: "linear" }}>
          <Loader2 className="h-6 w-6 text-primary" aria-hidden="true" />
        </motion.span>
        <p className="text-sm text-muted-foreground">Writing quiz questions from the actual code...</p>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <Button size="sm" variant="outline" onClick={start}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-3">
      {allAnswered && (
        <div className="glass flex items-center justify-between rounded-md p-3">
          <p className="text-sm font-medium text-foreground">
            You scored {correctCount} / {questions.length}
          </p>
          <Button size="sm" variant="outline" onClick={retake}>
            <RotateCcw className="mr-1 h-3.5 w-3.5" />
            Retake
          </Button>
        </div>
      )}
      {questions.map((q, qIndex) => {
        const selected = answers[qIndex];
        const isAnswered = selected !== null;
        return (
          <div key={qIndex} className="glass rounded-md p-3">
            <p className="mb-2 text-sm font-medium text-foreground">
              {qIndex + 1}. {q.question}
            </p>
            <div className="space-y-1.5">
              {q.options.map((option, oIndex) => {
                const isCorrectOption = oIndex === q.correct_index;
                const isSelected = selected === oIndex;
                return (
                  <button
                    key={oIndex}
                    type="button"
                    onClick={() => selectAnswer(qIndex, oIndex)}
                    disabled={isAnswered}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-md border px-3 py-1.5 text-left text-xs transition-colors",
                      !isAnswered &&
                        "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground",
                      isAnswered && isCorrectOption && "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
                      isAnswered &&
                        isSelected &&
                        !isCorrectOption &&
                        "border-destructive/50 bg-destructive/10 text-destructive",
                      isAnswered && !isSelected && !isCorrectOption && "border-border text-muted-foreground opacity-60"
                    )}
                  >
                    {option}
                    {isAnswered && isCorrectOption && <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                    {isAnswered && isSelected && !isCorrectOption && (
                      <X className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    )}
                  </button>
                );
              })}
            </div>
            {isAnswered && (
              <motion.p
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.15 }}
                className="mt-2 text-xs leading-relaxed text-muted-foreground"
              >
                {q.explanation}
              </motion.p>
            )}
          </div>
        );
      })}
    </div>
  );
}
