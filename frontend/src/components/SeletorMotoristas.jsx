// Escolha dos motoristas da roteirização (campo de pesquisa com seleção múltipla). Só os ATIVOS aparecem; a busca olha nome e
// código; com loja escolhida, "Desta loja" vem primeiro e "Outros motoristas" depois (a busca alcança todos). A lista renderiza
// no máximo LIMITE_DA_LISTA itens, então funciona com centenas de motoristas.
// "Marcar todos" vale só para os motoristas da loja escolhida; "Limpar" desmarca tudo.
import { useMemo, useState } from 'react';
import ComboboxMultiplo from './ComboboxMultiplo';
import { agruparParaRoteirizacao, avisoDeLimite, motoristasDaLoja } from '../services/motoristas';
import { rotuloDoMotorista, alternarMarcacao, marcarVarios, motoristasMarcados, etiquetaDoMotorista } from '../services/selecaoMotoristas';

export default function SeletorMotoristas({ motoristas, lojaId, rotasHoje, selecionados, onMudar }) {
  const [busca, setBusca] = useState('');

  const resultado = useMemo(() => agruparParaRoteirizacao(motoristas, lojaId, busca), [motoristas, lojaId, busca]);
  const grupos = useMemo(
    () => resultado.grupos.map((g) => ({
      chave: g.chave,
      titulo: g.titulo,
      itens: g.itens.map((m) => ({ id: m.id, rotulo: rotuloDoMotorista(m, rotasHoje[String(m.id)] || 0), detalhe: m.codigo || '' })),
    })),
    [resultado, rotasHoje],
  );
  const chips = useMemo(
    () => motoristasMarcados(motoristas, selecionados).map((m) => ({ id: m.id, rotulo: etiquetaDoMotorista(m) })),
    [motoristas, selecionados],
  );
  const daLoja = useMemo(() => motoristasDaLoja(motoristas, lojaId), [motoristas, lojaId]);

  const botao = 'px-2 py-0.5 rounded border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-slate-300';

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <button
          type="button"
          onClick={() => onMudar(marcarVarios(selecionados, daLoja.map((m) => m.id)))}
          disabled={daLoja.length === 0}
          title={lojaId === null ? 'Escolha a loja de origem para marcar os motoristas dela' : undefined}
          className={botao}
        >
          Marcar todos desta loja{lojaId !== null ? ` (${daLoja.length})` : ''}
        </button>
        <button type="button" onClick={() => onMudar([])} disabled={selecionados.length === 0} className={botao}>
          Limpar
        </button>
      </div>

      <ComboboxMultiplo
        rotulo="Motoristas da roteirização"
        placeholder="Pesquise o motorista (nome ou código)"
        grupos={grupos}
        selecionados={selecionados}
        chips={chips}
        busca={busca}
        onBusca={setBusca}
        onAlternar={(id) => onMudar(alternarMarcacao(selecionados, id))}
        onRemover={(id) => onMudar(selecionados.filter((x) => x !== id))}
        aviso={avisoDeLimite(resultado)}
        textoVazio="Nenhum motorista encontrado"
      />
    </div>
  );
}
