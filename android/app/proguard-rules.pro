# gomobile köprüsü (libv2ray + go.Seq) yansıma ile çağrılır
-keep class go.** { *; }
-keep class libv2ray.** { *; }
-keepclasseswithmembernames class * { native <methods>; }
-repackageclasses ''
-allowaccessmodification
