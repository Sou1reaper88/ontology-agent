/** Keep Ant Design validation rejections inside the action that initiated them. */
export async function validatedFormValues<T>(validate: () => Promise<T>): Promise<T | null> {
  try {
    return await validate();
  } catch {
    return null;
  }
}
