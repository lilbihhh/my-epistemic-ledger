export default function Home() {
  return (
    <main style={{ padding: '2rem', fontFamily: 'system-ui, sans-serif', maxWidth: '800px', margin: '0 auto' }}>
      <h1>Epistemic Ledger Pipeline</h1>
      <p>Auditable reasoning chains with LangChain &amp; LangGraph</p>
      
      <section style={{ marginTop: '2rem' }}>
        <h2>About</h2>
        <p>
          This project implements an auditable pipeline for tracking epistemic decisions 
          and reasoning chains using LangChain and LangGraph.
        </p>
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2>Features</h2>
        <ul>
          <li>Auditable reasoning chains</li>
          <li>Confidence scoring</li>
          <li>Evidence tracking</li>
          <li>Full audit trail</li>
        </ul>
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2>Python Backend</h2>
        <p>
          The core pipeline is implemented in Python. See <code>main.py</code> for the 
          implementation details.
        </p>
      </section>
    </main>
  );
}
