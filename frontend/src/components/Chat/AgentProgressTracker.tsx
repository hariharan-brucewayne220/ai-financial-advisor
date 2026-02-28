/**
 * AgentProgressTracker Component
 *
 * Shows real-time agent execution steps during answer generation.
 * Displays which node in the LangGraph is currently executing.
 *
 * **Educational:**
 * This visualizes the agentic pipeline:
 * 1. classify - Understand query type
 * 2. retrieve - Find relevant documents (hybrid: dense + sparse + HyDE)
 * 3. rerank - Improve result quality with cross-encoder
 * 4. compress - Reduce tokens with LLMLingua
 * 5. generate - Create answer with GPT-4o
 * 6. score - Validate faithfulness with NLI
 * 7. format - Add citations and formatting
 */

import React from 'react'

interface AgentProgressTrackerProps {
  currentStep: string
}

const AgentProgressTracker: React.FC<AgentProgressTrackerProps> = ({ currentStep }) => {
  const steps = [
    { name: 'classify', label: 'Analyzing Query', icon: '🔍' },
    { name: 'retrieve', label: 'Searching Documents', icon: '📚' },
    { name: 'rerank', label: 'Ranking Results', icon: '⭐' },
    { name: 'compress', label: 'Optimizing Context', icon: '📦' },
    { name: 'generate', label: 'Generating Answer', icon: '✍️' },
    { name: 'score', label: 'Verifying Faithfulness', icon: '✅' },
    { name: 'format', label: 'Formatting Response', icon: '🎯' },
  ]

  const currentIndex = steps.findIndex(s => s.name === currentStep)

  return (
    <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
      <p className="text-sm font-semibold text-blue-900 mb-3">Agent Pipeline Progress</p>
      <div className="space-y-2">
        {steps.map((step, idx) => {
          let status = 'pending'
          if (idx < currentIndex) status = 'completed'
          if (idx === currentIndex) status = 'current'

          const statusClass =
            status === 'completed'
              ? 'bg-green-100 text-green-700 border-green-300'
              : status === 'current'
              ? 'bg-blue-100 text-blue-700 border-blue-300 animate-pulse'
              : 'bg-gray-100 text-gray-500 border-gray-200'

          return (
            <div key={step.name} className={`flex items-center gap-3 px-3 py-2 rounded border ${statusClass}`}>
              <span className="text-lg">{step.icon}</span>
              <span className="text-sm font-medium flex-1">{step.label}</span>
              {status === 'completed' && <span className="text-green-600">✓</span>}
              {status === 'current' && <span className="animate-spin">⟳</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default AgentProgressTracker
