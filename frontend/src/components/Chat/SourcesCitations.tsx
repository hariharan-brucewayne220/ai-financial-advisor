/**
 * SourcesCitations Component
 *
 * Displays which document chunks were used to generate the answer.
 * Allows traceability and compliance auditing.
 */

import React from 'react'

interface SourcesCitationsProps {
  sources: string[]
}

const SourcesCitations: React.FC<SourcesCitationsProps> = ({ sources }) => {
  if (!sources || sources.length === 0) return null

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      // ignore
    }
  }

  return (
    <div className="text-sm text-gray-600 border-t pt-2 mt-2">
      <p className="font-semibold text-gray-700 mb-1">Sources</p>
      <div className="flex flex-wrap gap-2">
        {sources.map((source) => (
          <button
            key={source}
            onClick={() => copy(source)}
            className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs border border-blue-200 hover:bg-blue-100 transition-colors"
            title="Copy source id"
          >
            {source.substring(0, 8)}…
          </button>
        ))}
      </div>
    </div>
  )
}

export default SourcesCitations
