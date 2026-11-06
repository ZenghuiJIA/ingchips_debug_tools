export interface ProtocolField {
  name: string; offset: number; type: string; size?: number; endian?: 'little' | 'big'; scale?: number; bias?: number;
  bits?: { offset: number; width: number }; labels?: Record<string, string>;
}
export interface ProtocolSpec {
  schema_version: 1; name: string; header?: number[]; tail?: number[]; fixed_length?: number;
  length_field?: { offset: number; size: number; adjustment?: number }; max_frame?: number;
  endian?: 'little' | 'big'; checksum?: { algorithm: string; offset: number; start?: number; end?: number; endian?: 'little' | 'big' };
  fields: ProtocolField[]; partial_timeout_ms?: number;
}
export interface ProtocolFrame { offset: number; data: string; valid: boolean; fields: Record<string, unknown>; labels: Record<string, string>; error: string | null }
export const exampleProtocol: ProtocolSpec = {
  schema_version: 1, name: 'AA55 示例（按实际协议修改）', header: [170, 85], fixed_length: 7, endian: 'little',
  checksum: { algorithm: 'sum8', offset: 6, start: 0 }, partial_timeout_ms: 1000,
  fields: [{ name: 'seq', offset: 2, type: 'uint8' }, { name: 'value', offset: 3, type: 'int16' }, { name: 'status', offset: 5, type: 'uint8' }],
};
export function protocolHilDocument(port: string, baud: number, protocol: ProtocolSpec, values: Record<string, unknown>, expected: Record<string, unknown>, timeout: number) {
  return { schema_version: 2, name: protocol.name + ' 请求应答测试', steps: [{ id: 'request', action: 'protocol_request', enabled: true,
    timeout_ms: timeout, params: { port_name: port, baud_rate: baud, protocol: JSON.parse(JSON.stringify(protocol)), values, expected } }] };
}
