import { readFileSync } from "node:fs";

import type { JsonObject } from "../effect_program.ts";
import {
  AuthorityStoreProtocolError,
  canonicalAuthorityObject,
} from "./authority_store_codec.ts";

export const COORDINATION_STATE_CONTRACT_SCHEMA =
  "loopx_coordination_state_contract_v0";

interface RecordContract {
  readonly fields: readonly string[];
  readonly required_fields: readonly string[];
}

interface TodoRecordContract extends RecordContract {
  readonly schema_version: string;
  readonly item_schema_version: string;
}

interface CoordinationStateContract {
  readonly schema_version: typeof COORDINATION_STATE_CONTRACT_SCHEMA;
  readonly todo_read_record: TodoRecordContract;
  readonly compatibility: {
    readonly unknown_field_policy: "reject";
    readonly field_removal_policy: "maintainer_approval_required";
    readonly markdown_role: "human_workbench_and_compatibility_projection";
  };
}

function stringList(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.length === 0 ||
      value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new AuthorityStoreProtocolError(`${label} must contain non-empty strings`);
  }
  if (new Set(value).size !== value.length) {
    throw new AuthorityStoreProtocolError(`${label} must not contain duplicates`);
  }
  return Object.freeze([...value] as string[]);
}

function recordContract(value: unknown, label: string): RecordContract {
  const record = canonicalAuthorityObject(value, label);
  return Object.freeze({
    fields: stringList(record.fields, `${label}.fields`),
    required_fields: stringList(record.required_fields, `${label}.required_fields`),
  });
}

function loadCoordinationStateContract(): CoordinationStateContract {
  const raw = canonicalAuthorityObject(JSON.parse(readFileSync(
    new URL("./coordination_state_contract_v0.json", import.meta.url),
    "utf8",
  )), "coordination state contract");
  if (raw.schema_version !== COORDINATION_STATE_CONTRACT_SCHEMA) {
    throw new AuthorityStoreProtocolError("coordination state contract schema mismatch");
  }
  const todo = canonicalAuthorityObject(raw.todo_read_record, "todo_read_record");
  const compatibility = canonicalAuthorityObject(raw.compatibility, "compatibility");
  if (typeof todo.schema_version !== "string" ||
      typeof todo.item_schema_version !== "string" ||
      compatibility.unknown_field_policy !== "reject" ||
      compatibility.field_removal_policy !== "maintainer_approval_required" ||
      compatibility.markdown_role !== "human_workbench_and_compatibility_projection") {
    throw new AuthorityStoreProtocolError("coordination state contract policy mismatch");
  }
  return Object.freeze({
    schema_version: COORDINATION_STATE_CONTRACT_SCHEMA,
    todo_read_record: Object.freeze({
      ...recordContract(todo, "todo_read_record"),
      schema_version: todo.schema_version,
      item_schema_version: todo.item_schema_version,
    }),
    compatibility: Object.freeze({
      unknown_field_policy: "reject",
      field_removal_policy: "maintainer_approval_required",
      markdown_role: "human_workbench_and_compatibility_projection",
    }),
  });
}

export const COORDINATION_STATE_CONTRACT = loadCoordinationStateContract();
export const TODO_CANONICAL_READ_RECORD_SCHEMA =
  COORDINATION_STATE_CONTRACT.todo_read_record.schema_version;
export const TODO_ITEM_SCHEMA =
  COORDINATION_STATE_CONTRACT.todo_read_record.item_schema_version;
export const TODO_CANONICAL_READ_RECORD_FIELDS =
  COORDINATION_STATE_CONTRACT.todo_read_record.fields;
export const TODO_CANONICAL_REQUIRED_READ_FIELDS =
  COORDINATION_STATE_CONTRACT.todo_read_record.required_fields;

export function canonicalCoordinationRecord(
  value: unknown,
  contract: RecordContract,
  label: string,
): JsonObject {
  const record = canonicalAuthorityObject(value, label);
  const allowed = new Set(contract.fields);
  const unexpected = Object.keys(record)
    .filter((field) => !allowed.has(field))
    .sort((left, right) => left.localeCompare(right));
  if (unexpected.length > 0) {
    throw new AuthorityStoreProtocolError(
      `${label} has unversioned fields: ${unexpected.join(", ")}`,
    );
  }
  const missing = contract.required_fields.filter((field) => !(field in record));
  if (missing.length > 0) {
    throw new AuthorityStoreProtocolError(
      `${label} omits required fields: ${missing.join(", ")}`,
    );
  }
  return canonicalAuthorityObject(Object.fromEntries(
    contract.fields.flatMap((field) => field in record ? [[field, record[field]]] : []),
  ), label);
}

export function canonicalCoordinationTodoRecord(
  value: unknown,
  label = "coordination Todo read record",
): JsonObject {
  const record = canonicalCoordinationRecord(
    value,
    COORDINATION_STATE_CONTRACT.todo_read_record,
    label,
  );
  if (record.schema_version !== TODO_ITEM_SCHEMA ||
      (record.role !== "user" && record.role !== "agent") ||
      typeof record.status !== "string" || record.status.length === 0 ||
      typeof record.done !== "boolean" || typeof record.text !== "string" ||
      typeof record.archive_state !== "string" || record.archive_state.length === 0 ||
      typeof record.source_section !== "string" || record.source_section.length === 0) {
    throw new AuthorityStoreProtocolError(`${label} has invalid required semantics`);
  }
  return record;
}
