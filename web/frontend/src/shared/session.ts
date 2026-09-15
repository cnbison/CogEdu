// 会话 hook：服务端权威校验（GET /api/auth/me），供各端 shell 守卫使用。
import { useQuery } from "@tanstack/react-query";
import { fetchSession, type PublicUser } from "./auth";

export const SESSION_QUERY_KEY = ["session"] as const;

/** 当前登录用户（服务端校验）。401 时 authFetch 已清会话并跳登录页，此处只会 throw。 */
export function useSession() {
  return useQuery<PublicUser>({
    queryKey: SESSION_QUERY_KEY,
    queryFn: fetchSession,
    retry: false,
    staleTime: 60_000,
  });
}
