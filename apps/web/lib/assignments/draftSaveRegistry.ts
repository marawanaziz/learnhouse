export type AssignmentDraftSave = () => Promise<void>

const assignmentDraftSaves = new Map<
  string,
  Map<string, AssignmentDraftSave>
>()

export function registerAssignmentDraftSave(
  assignmentUuid: string,
  taskUuid: string,
  save: AssignmentDraftSave
) {
  let taskSaves = assignmentDraftSaves.get(assignmentUuid)
  if (!taskSaves) {
    taskSaves = new Map()
    assignmentDraftSaves.set(assignmentUuid, taskSaves)
  }

  taskSaves.set(taskUuid, save)

  return () => {
    const currentTaskSaves = assignmentDraftSaves.get(assignmentUuid)
    if (currentTaskSaves?.get(taskUuid) !== save) return

    currentTaskSaves.delete(taskUuid)
    if (currentTaskSaves.size === 0) {
      assignmentDraftSaves.delete(assignmentUuid)
    }
  }
}

export async function flushAssignmentDraftSaves(assignmentUuid: string) {
  const taskSaves = assignmentDraftSaves.get(assignmentUuid)
  if (!taskSaves) return

  await Promise.all([...taskSaves.values()].map((save) => save()))
}
