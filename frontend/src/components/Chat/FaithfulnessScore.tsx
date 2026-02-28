/**
 * FaithfulnessScore Component
 *
 * Shows NLI entailment score (0.0-1.0) indicating how well answer
 * is grounded in retrieved documents.
 *
 * Educational: This badge demonstrates faithfulness verification - a key differentiator
 * in RAG systems. Instead of just trusting the LLM, we verify the answer is supported
 * by the retrieved context using Natural Language Inference.
 */

import React from 'react'

interface FaithfulnessScoreProps {
  score: number
  showLabel?: boolean
}

const FaithfulnessScore: React.FC<FaithfulnessScoreProps> = ({ score, showLabel = false }) => {
  // Determine color based on score
  let color = 'bg-red-100 text-red-700 border-red-300'
  let label = 'Low'

  if (score >= 0.8) {
    color = 'bg-green-100 text-green-700 border-green-300'
    label = 'High'
  } else if (score >= 0.6) {
    color = 'bg-yellow-100 text-yellow-700 border-yellow-300'
    label = 'Medium'
  }

  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border text-sm font-medium ${color}`}>
      <span>📊</span>
      <span>Confidence: {(score * 100).toFixed(0)}%</span>
      {showLabel && <span className="text-xs opacity-75">({label})</span>}
    </div>
  )
}

export default FaithfulnessScore
